"""dailylog 桌面应用入口：pywebview 窗口 + pystray 系统托盘。

- 关闭按钮 → 销毁窗口进零窗口挂起（进程常驻，定时记录继续）；托盘「打开程序」二次
  webview.start() 重建（pywebview 未文档化用法，依赖源码行为：最后窗口销毁 → start 返回）
- 托盘右键：打开程序 / 开始记录 / 退出程序（退出时停用定时记录）
- 打包后（frozen）任务计划调用本 exe 的 --capture 参数执行截屏分析

注：pywebview 6 移除了内置托盘，这里用 pystray 实现（标准组合方案）。
"""
import ctypes
import json
import shutil
import sys
import tempfile
import threading
import time
from pathlib import Path

import webview
from PIL import Image
import pystray

from core import config
import ui_api

_logger = config.setup_logging()


def _cleanup_stale_webview() -> None:
    """清理 pywebview 历史残留的临时 WebView2 数据目录（%TEMP%/tmp*/EBWebView，超 7 天）。

    老版本每次启动都在临时目录新建数据目录且不清理（累计可达数百 MB）；
    现已固定到 config.WEBVIEW_DIR，这里只做一次性历史清理，当前/近期目录不动。
    """
    base = Path(tempfile.gettempdir())
    cutoff = time.time() - 7 * 86400
    for d in base.iterdir():
        if not d.is_dir() or not d.name.startswith("tmp") or not (d / "EBWebView").is_dir():
            continue
        try:
            if d.stat().st_mtime < cutoff:
                shutil.rmtree(
                    d,
                    onexc=lambda _f, p, e: _logger.warning("清理 WebView2 残留失败 %s: %s", p, e),
                )
                _logger.info("已清理残留 WebView2 目录: %s", d)
        except OSError as e:
            _logger.warning("清理 WebView2 残留失败 %s: %s", d, e)


def resource_path(rel: str) -> Path:
    """打包后静态资源在 _MEIPASS 临时目录，开发期在源码目录。"""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / rel


def _cachebust_html() -> Path:
    """生成带资产版本号的 index.html 派生文件（static/index_cachebust.html）。

    WebView2 数据目录持久化（private_mode=False），会缓存旧 style.css/script.js，
    改完前端重启应用仍显示旧界面。这里按资产文件 mtime 给引用追加 ?v= 参数：
    文件一变 URL 即变，缓存自动失效，无需手动清缓存或改版本号。
    必须与资产同目录（pywebview 以 html 所在目录为服务根），否则相对引用失效。
    """
    src = resource_path("static/index.html")
    html = src.read_text(encoding="utf-8")
    for attr, asset in (("href=", "style.css"), ("src=", "script.js")):
        mtime = int((resource_path(f"static/{asset}")).stat().st_mtime)
        html = html.replace(f'{attr}"{asset}"', f'{attr}"{asset}?v={mtime}"')
    out = resource_path("static/index_cachebust.html")
    out.write_text(html, encoding="utf-8")
    return out


class AppApi(ui_api.Api):
    """在 ui_api 基础上补充无边框窗口的控制方法（供前端标题栏按钮调用）。"""

    def __init__(self, window):
        super().__init__()
        self._window = window
        self._maximized = False
        self._tray_refresh = lambda: None
        self._hide_to_tray = lambda: None

    def set_tray_refresh(self, fn) -> None:
        """标题栏总开关切换后，同步托盘菜单文案的回调。"""
        self._tray_refresh = fn

    def set_hide_to_tray(self, fn) -> None:
        """标题栏 ✕ 触发的托盘化回调（销毁唯一窗口进零窗口挂起，见 main）。"""
        self._hide_to_tray = fn

    def toggle_recording(self) -> dict:
        result = super().toggle_recording()
        try:
            self._tray_refresh()
        except Exception:  # noqa: BLE001
            pass
        return result

    def manual_capture(self) -> dict:
        """设置页按钮触发：后台线程执行截屏分析（同步跑会阻塞 JS 桥，
        期间最小化/最大化等所有窗口控制全部无响应），完成后前端 toast。"""
        def run():
            try:
                from core import capture  # noqa: PLC0415
                code = capture.main(force=True)
                msg = "记录完成" if code == 0 else "记录失败，详见 dailylog.log"
            except Exception as e:  # noqa: BLE001
                _logger.error("手动截屏失败: %s", e)
                msg = f"记录失败: {e}"
            try:
                self._window.evaluate_js(f"toast({json.dumps(msg)})")
            except Exception:  # noqa: BLE001 窗口可能已关闭
                pass
        threading.Thread(target=run, daemon=True).start()
        return {"ok": True}

    def export_data_dialog(self) -> dict:
        """数据管理·导出：系统保存对话框选路径后写 JSON 备份。

        pywebview 的 create_file_dialog 在 winforms 下返回 (路径,) 元组，取消返回 None。
        """
        try:
            result = self._window.create_file_dialog(
                webview.SAVE_DIALOG, save_filename="dailylog-backup.json",
                file_types=("JSON 备份 (*.json)",),
            )
        except Exception as e:  # noqa: BLE001
            _logger.error("导出对话框失败: %s", e)
            return {"ok": False, "error": str(e)}
        if not result:
            return {"ok": False, "cancelled": True}
        return self.export_data(result[0])

    def import_data_dialog(self) -> dict:
        """数据管理·导入：系统打开对话框选备份文件后恢复。"""
        try:
            result = self._window.create_file_dialog(
                webview.OPEN_DIALOG, file_types=("JSON 备份 (*.json)",),
            )
        except Exception as e:  # noqa: BLE001
            _logger.error("导入对话框失败: %s", e)
            return {"ok": False, "error": str(e)}
        if not result:
            return {"ok": False, "cancelled": True}
        return self.import_data(result[0])

    def backup_dir_dialog(self) -> dict:
        """设置页·自动备份：系统文件夹选择对话框选备份目录并保存。"""
        try:
            result = self._window.create_file_dialog(webview.FOLDER_DIALOG)
        except Exception as e:  # noqa: BLE001
            _logger.error("备份目录对话框失败: %s", e)
            return {"ok": False, "error": str(e)}
        if not result:
            return {"ok": False, "cancelled": True}
        return self.set_backup_settings(backup_dir=result[0])

    def copy_report(self, name: str, export_format: str) -> dict:
        """把报告复制为邮件纯文本或 Windows 富文本。"""
        from core import report_export  # noqa: PLC0415
        report = self.get_report(name)
        if not report.get("ok"):
            return report
        if export_format not in {"text", "html"}:
            return {"ok": False, "error": "不支持的复制格式"}
        try:
            plain_text = report_export.email_text(report["content"])
            rich_text = report_export.rich_html(report["content"])
            _copy_report_to_clipboard(plain_text, rich_text if export_format == "html" else None)
        except RuntimeError as exc:
            _logger.error("复制报告失败: %s", exc)
            return {"ok": False, "error": str(exc)}
        return {"ok": True, "format": export_format}

    def export_report_pdf_dialog(self, name: str) -> dict:
        """用原生另存为对话框导出报告 PDF。"""
        from core import report_export  # noqa: PLC0415
        report = self.get_report(name)
        if not report.get("ok"):
            return report
        try:
            result = self._window.create_file_dialog(
                webview.SAVE_DIALOG,
                save_filename=f"{Path(name).stem}.pdf",
                file_types=("PDF 文件 (*.pdf)",),
            )
        except Exception as exc:  # noqa: BLE001
            _logger.error("PDF 导出对话框失败: %s", exc)
            return {"ok": False, "error": str(exc)}
        if not result:
            return {"ok": False, "cancelled": True}
        destination = Path(result[0])
        if destination.suffix.lower() != ".pdf":
            destination = destination.with_suffix(".pdf")
        try:
            report_export.write_pdf(report["content"], destination)
        except RuntimeError as exc:
            _logger.error("PDF 导出失败: %s", exc)
            return {"ok": False, "error": str(exc)}
        return {"ok": True, "path": str(destination)}

    def minimize(self) -> None:
        self._window.minimize()

    def maximize(self) -> None:
        """最大化 / 还原 切换（pywebview 的 maximize 是幂等的，不会自动还原）。"""
        if self._maximized:
            self._window.restore()
        else:
            self._window.maximize()
        self._maximized = not self._maximized

    def close_window(self) -> None:
        """标题栏 ✕：托盘化（销毁唯一窗口释放内存，重开时二次 start 重建）。"""
        self._hide_to_tray()

    def move(self, x: int, y: int) -> None:
        """标题栏拖拽移动窗口（frameless 无原生拖拽，由前端手动驱动）。"""
        self._window.move(int(x), int(y))

    def resize(self, w: int, h: int) -> None:
        """右下角手柄缩放窗口（frameless 无原生缩放手柄）。"""
        self._window.resize(int(w), int(h))


def main() -> None:
    try:
        from core import capture  # noqa: PLC0415 延迟导入：截屏依赖（mss）只在需要时进内存
        capture.cleanup_expired()  # 启动时按保留天数清理过期数据（每天一次）
    except Exception as e:  # noqa: BLE001
        _logger.error("启动数据清理失败: %s", e)
    try:
        _cleanup_stale_webview()  # 清理历史残留的临时 WebView2 目录
    except Exception as e:  # noqa: BLE001
        _logger.error("残留 WebView2 目录清理失败: %s", e)

    api = AppApi(None)

    reopen = threading.Event()  # 托盘「打开程序」→ 唤醒挂起的主循环重建窗口

    def _create_window(hidden: bool):
        """创建主窗口（首次启动与零窗口重开共用同一套事件绑定）。"""
        try:
            page = str(_cachebust_html())
        except Exception as e:  # noqa: BLE001 生成失败不阻塞启动，退回原始文件（可能吃缓存）
            _logger.error("生成缓存穿透页面失败，退回原始 index.html: %s", e)
            page = str(resource_path("static/index.html"))
        win = webview.create_window(
            config.APP_TITLE,
            page,
            width=1280, height=800, min_size=(960, 600),
            frameless=True,
            background_color="#060a09",
            hidden=hidden,
            js_api=api,
        )
        api._window = win
        api._maximized = False

        def _enable_taskbar_minimize():
            """frameless 被 WinForms 去掉 WS_MINIMIZEBOX 样式位，任务栏点击不会最小化，补回。"""
            user32 = ctypes.windll.user32
            hwnd = ctypes.c_void_p(win.native.Handle.ToInt64())
            user32.GetWindowLongW.argtypes = [ctypes.c_void_p, ctypes.c_int]
            user32.GetWindowLongW.restype = ctypes.c_long
            user32.SetWindowLongW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_long]
            style = user32.GetWindowLongW(hwnd, -16)
            user32.SetWindowLongW(hwnd, -16, style | 0x00020000)

        def on_loaded():
            _enable_taskbar_minimize()
            if getattr(win, "_pending_show", False):
                win._pending_show = False
                win.show()

        win.events.loaded += on_loaded
        return win

    def hide_to_tray():
        """托盘化的实际动作：直接销毁唯一窗口（零窗口方案，不预建隐藏窗口）。

        最后一个窗口销毁后 webview.start() 返回、WebView2 全家桶进程全部退出，
        主循环随即挂起等 reopen；重开由托盘「打开程序」二次调用 webview.start()。
        """
        win = window
        if win is None:
            return
        try:
            win.destroy()
        except Exception as e:  # noqa: BLE001
            _logger.error("托盘化销毁窗口失败: %s", e)

    api.set_hide_to_tray(hide_to_tray)

    force_exit = False
    tray = None

    def on_show(icon=None, item=None):
        # 只显示窗口，不碰任务状态：用户上次"停止"的选择必须被尊重（见 startup_enable）。
        win = window
        if win is not None and not win.events.closed.is_set():
            try:
                win.show()  # 页面尚未加载完时由 on_loaded 兜底显示
                return
            except Exception as e:  # noqa: BLE001
                _logger.error("显示窗口失败: %s", e)
        reopen.set()  # 零窗口挂起中：唤醒主循环二次 start() 重建窗口

    def run_capture_once(force: bool = False):
        """立即执行一次截屏分析（后台线程），结果弹 toast。force=True 跳过去重与空闲检查。"""
        def run():
            try:
                from core import capture  # noqa: PLC0415
                code = capture.main(force=force)
                msg = "记录完成" if code == 0 else "记录失败，详见 dailylog.log"
            except Exception as e:  # noqa: BLE001
                msg = f"记录失败: {e}"
            try:
                window.evaluate_js(f"toast({json.dumps(msg)})")
            except Exception:  # noqa: BLE001
                pass
        threading.Thread(target=run, daemon=True).start()

    def start_enter_listener():
        """回车键快速记录：全局监听回车键（pynput），间隔内连续按键只记录第一次。

        监听线程常驻（进程不退出，托盘化后仍生效）；开关/间隔每次按键实时读
        settings.json，设置页改动无需重启监听。pynput 缺失时仅记录错误，不影响其他功能。
        """
        try:
            from pynput import keyboard  # noqa: PLC0415
        except ImportError as e:
            _logger.error("回车键快速记录不可用（未安装 pynput）: %s", e)
            return
        last_capture = [0.0]

        def on_press(key):
            try:
                if key != keyboard.Key.enter:
                    return
                if not config.SETTINGS.get("enter_capture_enabled"):
                    return
                interval = config.SETTINGS.get("enter_capture_interval", 15)
                now = time.time()
                if now - last_capture[0] < interval:
                    return
                last_capture[0] = now
                _logger.info("回车键快速记录触发")
                run_capture_once(force=True)
            except Exception as e:  # noqa: BLE001
                _logger.error("回车键监听回调异常: %s", e)

        try:
            listener = keyboard.Listener(on_press=on_press)
            listener.daemon = True
            listener.start()
            _logger.info("回车键快速记录监听已启动")
        except Exception as e:  # noqa: BLE001
            _logger.error("回车键监听启动失败: %s", e)

    def refresh_ui(msg=None):
        try:
            js = "refreshStatus();"
            if msg:
                js = f"toast({json.dumps(msg)}); " + js
            window.evaluate_js(js)
        except Exception:  # noqa: BLE001
            pass

    def on_toggle_recording(icon=None, item=None):
        """开始/停止定时记录开关：启用并立即截屏一次，或停用；持久化用户选择。"""
        recording = ui_api.task_is_enabled()
        if recording:
            ui_api.disable_task()
            msg = "定时记录已停止"
        else:
            ui_api.enable_task()
            msg = "定时记录已开始"
            run_capture_once()  # 立即截屏一次，马上能看到效果
        ui_api.persist_recording_choice(not recording)
        tray.title = TRAY_STOPPED if recording else TRAY_RUNNING  # recording 是切换前状态，标题需反映切换后
        tray.menu = build_menu()
        refresh_ui(msg)

    def build_menu():
        recording = ui_api.task_is_enabled()
        return pystray.Menu(
            pystray.MenuItem("打开程序", on_show, default=True),
            pystray.MenuItem("停止记录" if recording else "开始记录", on_toggle_recording),
            pystray.MenuItem("退出程序", on_quit),
        )

    def on_quit(icon=None, item=None):
        nonlocal force_exit
        force_exit = True
        try:
            ui_api.disable_task()  # 退出程序 → 停用定时记录
        except Exception as e:  # noqa: BLE001
            _logger.error("退出时停用定时任务失败: %s", e)
        if tray:
            tray.stop()
        reopen.set()  # 唤醒可能正挂起的主循环，使其看到 force_exit 后退出
        win = window
        if win is not None:
            try:
                win.destroy()
            except Exception:  # noqa: BLE001
                pass

    TRAY_RUNNING = "dailylog · 今日轨迹（定时记录运行中）"
    TRAY_STOPPED = "dailylog · 今日轨迹（定时记录已停止）"

    tray = pystray.Icon(
        "dailylog",
        Image.open(resource_path("static/assets/icon.ico")),
        TRAY_RUNNING,
        menu=build_menu(),
    )
    threading.Thread(target=tray.run, daemon=True).start()

    def refresh_tray_menu():
        """同步托盘标题与菜单文案到任务真实状态（标题栏切换后也调用）。"""
        if tray is None:
            return
        try:
            tray.title = TRAY_RUNNING if ui_api.task_is_enabled() else TRAY_STOPPED
            tray.menu = build_menu()
        except Exception as e:  # noqa: BLE001
            _logger.error("同步托盘菜单失败: %s", e)

    api.set_tray_refresh(refresh_tray_menu)

    def startup_enable():
        """启动时按用户上次的选择恢复定时记录（默认开启）；完成后同步托盘菜单文案。"""
        try:
            if config.SETTINGS.get("recording_enabled", True):
                ui_api.enable_task()
            tray.title = TRAY_RUNNING if ui_api.task_is_enabled() else TRAY_STOPPED
            tray.menu = build_menu()
        except Exception as e:  # noqa: BLE001
            _logger.error("启动恢复定时任务失败: %s", e)

    def startup_usage():
        """启动时按设置确保应用时长采样任务：开启则创建（幂等），关闭则停用。"""
        try:
            if config.SETTINGS.get("usage_enabled", True):
                ui_api.ensure_usage_task()
            else:
                ui_api._set_task_enabled(False, ui_api.USAGE_TASK_NAME)
        except Exception as e:  # noqa: BLE001
            _logger.error("启动恢复应用时长采样任务失败: %s", e)

    def startup_backup():
        """启动时按设置确保每周自动备份任务：开启且已选目录则创建（幂等），关闭则停用。"""
        try:
            backup_is_configured = config.SETTINGS.get("backup_enabled", True) and config.SETTINGS.get("backup_dir")
            if not backup_is_configured and not ui_api.task_exists(ui_api.BACKUP_TASK_NAME):
                _logger.info("自动备份任务不存在，无需在启动时停用")
                return
            if config.SETTINGS.get("backup_enabled", True) and config.SETTINGS.get("backup_dir"):
                ui_api.ensure_backup_task()
            else:
                ui_api._set_task_enabled(False, ui_api.BACKUP_TASK_NAME)
        except Exception as e:  # noqa: BLE001
            _logger.error("启动恢复自动备份任务失败: %s", e)

    threading.Thread(target=startup_enable, daemon=True).start()
    threading.Thread(target=startup_usage, daemon=True).start()
    threading.Thread(target=startup_backup, daemon=True).start()

    start_enter_listener()  # 回车键快速记录（全局监听，常驻）

    def run_test_loop():
        """测试模式：秒级循环截屏（任务计划最小只能 1 分钟）。清除设置即停。"""
        secs = config.SETTINGS.get("test_interval_seconds")
        _logger.info("测试模式：每 %s 秒截屏一次（设置页改回分钟即退出）", secs)
        from core import capture  # noqa: PLC0415
        while True:
            secs = config.SETTINGS.get("test_interval_seconds")
            if not secs:
                _logger.info("测试模式已退出")
                break
            try:
                capture.main()
            except Exception as e:  # noqa: BLE001
                _logger.error("测试截屏失败: %s", e)
            time.sleep(int(secs))

    if config.SETTINGS.get("test_interval_seconds"):
        threading.Thread(target=run_test_loop, daemon=True).start()

    # 零窗口主循环：唯一窗口销毁后 start() 返回（pywebview 6 行为，源码确认），
    # 挂起等 reopen；重开时二次调用 start() 属未文档化用法——windows 列表随窗口关闭
    # 清空（winforms.py on_close）、uid 重新取 master、全局 HTTP server 与 WinForms
    # 初始化均可复用，「关闭↔打开」循环稳定性需实测观察本日志
    # storage_path 固定 WebView2 数据目录：避免每次启动建随机临时目录（冷启动 + 磁盘残留）
    # private_mode=False：默认 True 时 localStorage 不跨进程持久化，前端皮肤选择重启即丢
    while not force_exit:
        window = _create_window(hidden=True)  # 页面加载完成后再显示，避免空窗口闪烁
        window._pending_show = True
        webview.start(debug=False, storage_path=str(config.WEBVIEW_DIR), private_mode=False)
        window = None
        if force_exit:
            break
        reopen.clear()
        _logger.info("零窗口挂起：WebView2 进程已全部退出，等待托盘「打开程序」唤醒")
        reopen.wait()

    _logger.info("主循环退出")


def _copy_report_to_clipboard(plain_text: str, rich_html: str | None) -> None:
    """同时写入 Unicode 文本与 Windows HTML Clipboard Format。"""
    try:
        import win32clipboard
    except ImportError as exc:
        raise RuntimeError("缺少 Windows 剪贴板组件") from exc

    if rich_html is None:
        _write_text_clipboard(win32clipboard, plain_text)
        return

    start_marker = "<!--StartFragment-->"
    end_marker = "<!--EndFragment-->"
    document = f"<html><body>{start_marker}{rich_html}{end_marker}</body></html>"
    header_template = (
        "Version:0.9\r\n"
        "StartHTML:{start_html:010d}\r\n"
        "EndHTML:{end_html:010d}\r\n"
        "StartFragment:{start_fragment:010d}\r\n"
        "EndFragment:{end_fragment:010d}\r\n"
    )
    blank_header = header_template.format(start_html=0, end_html=0, start_fragment=0, end_fragment=0)
    start_html = len(blank_header.encode("utf-8"))
    document_bytes = document.encode("utf-8")
    marker_start_bytes = start_marker.encode("utf-8")
    marker_end_bytes = end_marker.encode("utf-8")
    fragment_start = start_html + document_bytes.index(marker_start_bytes) + len(marker_start_bytes)
    fragment_end = start_html + document_bytes.index(marker_end_bytes)
    header = header_template.format(
        start_html=start_html,
        end_html=start_html + len(document_bytes),
        start_fragment=fragment_start,
        end_fragment=fragment_end,
    )
    html_format = win32clipboard.RegisterClipboardFormat("HTML Format")
    try:
        win32clipboard.OpenClipboard()
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardData(win32clipboard.CF_UNICODETEXT, plain_text)
        win32clipboard.SetClipboardData(html_format, header.encode("utf-8") + document_bytes)
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError("无法写入 Windows 剪贴板") from exc
    finally:
        try:
            win32clipboard.CloseClipboard()
        except Exception:  # noqa: BLE001
            pass


def _write_text_clipboard(win32clipboard, plain_text: str) -> None:
    try:
        win32clipboard.OpenClipboard()
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardData(win32clipboard.CF_UNICODETEXT, plain_text)
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError("无法写入 Windows 剪贴板") from exc
    finally:
        try:
            win32clipboard.CloseClipboard()
        except Exception:  # noqa: BLE001
            pass


if __name__ == "__main__":
    if "--capture" in sys.argv:
        from core import capture
        sys.exit(capture.main())
    if "--usage" in sys.argv:
        from core import usage
        sys.exit(usage.main())
    if "--backup" in sys.argv:  # 每周自动备份：任务计划调 exe --backup
        from core import backup
        sys.exit(backup.main())
    if "--diag" in sys.argv:  # 打包诊断：从控制台打印 get_config 与 NextRunTime 异常
        import json as _json
        import traceback as _tb
        try:
            print("task_next_run 直接调用:", repr(ui_api.task_next_run()))
        except Exception:  # noqa: BLE001
            _tb.print_exc()
        try:
            print(_json.dumps(ui_api.Api().get_config(), ensure_ascii=False, indent=2))
        except Exception:  # noqa: BLE001
            _tb.print_exc()
        sys.exit(0)
    main()
