"""dailylog 桌面应用入口：pywebview 窗口 + pystray 系统托盘。

- 关闭按钮 → 最小化到托盘（进程常驻，定时记录继续）
- 托盘右键：打开程序 / 开始记录 / 退出程序（退出时停用定时记录）
- 打包后（frozen）任务计划调用本 exe 的 --capture 参数执行截屏分析

注：pywebview 6 移除了内置托盘，这里用 pystray 实现（标准组合方案）。
"""
import json
import sys
import threading
import time
from pathlib import Path

import webview
from PIL import Image
import pystray

import capture
import config
import ui_api

BASE_DIR = Path(__file__).resolve().parent
_logger = config.setup_logging()


def resource_path(rel: str) -> Path:
    """打包后静态资源在 _MEIPASS 临时目录，开发期在源码目录。"""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / rel


class AppApi(ui_api.Api):
    """在 ui_api 基础上补充无边框窗口的控制方法（供前端标题栏按钮调用）。"""

    def __init__(self, window):
        super().__init__()
        self._window = window
        self._maximized = False
        self._tray_refresh = lambda: None

    def set_tray_refresh(self, fn) -> None:
        """标题栏总开关切换后，同步托盘菜单文案的回调。"""
        self._tray_refresh = fn

    def toggle_recording(self) -> dict:
        result = super().toggle_recording()
        try:
            self._tray_refresh()
        except Exception:  # noqa: BLE001
            pass
        return result

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
        """标题栏 ✕：最小化到托盘（pywebview 6 的 Window 没有 close()，直接 hide）。"""
        self._window.hide()

    def move(self, x: int, y: int) -> None:
        """标题栏拖拽移动窗口（frameless 无原生拖拽，由前端手动驱动）。"""
        self._window.move(int(x), int(y))

    def resize(self, w: int, h: int) -> None:
        """右下角手柄缩放窗口（frameless 无原生缩放手柄）。"""
        self._window.resize(int(w), int(h))


def main() -> None:
    api = AppApi(None)  # 窗口对象在 create_window 返回后回填
    window = webview.create_window(
        "dailylog · 今日轨迹",
        str(resource_path("static/index.html")),
        width=1280, height=800, min_size=(960, 600),
        frameless=True,
        background_color="#060a09",
        hidden=True,  # 页面加载完成后再显示，避免空窗口闪烁
        js_api=api,
    )
    api._window = window

    def on_loaded():
        window.show()

    window.events.loaded += on_loaded

    force_exit = False
    tray = None

    def on_closing():
        # 返回 False 取消关闭 → 最小化到托盘；托盘"退出程序"时放行
        if force_exit:
            return True
        window.hide()
        return False

    def on_show(icon=None, item=None):
        ui_api.enable_task()
        window.show()

    def run_capture_once():
        """立即执行一次截屏分析（后台线程），结果弹 toast。"""
        def run():
            try:
                code = capture.main()
                msg = "记录完成" if code == 0 else "记录失败，详见 dailylog.log"
            except Exception as e:  # noqa: BLE001
                msg = f"记录失败: {e}"
            try:
                window.evaluate_js(f"toast({json.dumps(msg)})")
            except Exception:  # noqa: BLE001
                pass
        threading.Thread(target=run, daemon=True).start()

    def refresh_ui(msg=None):
        try:
            js = "refreshStatus();"
            if msg:
                js = f"toast({json.dumps(msg)}); " + js
            window.evaluate_js(js)
        except Exception:  # noqa: BLE001
            pass

    def on_toggle_recording(icon=None, item=None):
        """开始/停止定时记录开关：启用并立即截屏一次，或停用。"""
        recording = ui_api.task_is_enabled()
        if recording:
            ui_api.disable_task()
            msg = "定时记录已停止"
        else:
            ui_api.enable_task()
            msg = "定时记录已开始"
            run_capture_once()  # 立即截屏一次，马上能看到效果
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
        window.destroy()

    window.events.closing += on_closing

    TRAY_RUNNING = "dailylog · 今日轨迹（定时记录运行中）"
    TRAY_STOPPED = "dailylog · 今日轨迹（定时记录已停止）"

    tray = pystray.Icon(
        "dailylog",
        Image.open(resource_path("static/assets/icon.ico")),
        TRAY_RUNNING,
        menu=build_menu(),
    )
    threading.Thread(target=tray.run, daemon=True).start()

    def startup_enable():
        """启动时恢复定时记录；完成后同步托盘菜单文案。"""
        try:
            ui_api.enable_task()
            tray.title = TRAY_RUNNING if ui_api.task_is_enabled() else TRAY_STOPPED
            tray.menu = build_menu()
        except Exception as e:  # noqa: BLE001
            _logger.error("启动恢复定时任务失败: %s", e)

    threading.Thread(target=startup_enable, daemon=True).start()

    def run_test_loop():
        """测试模式：秒级循环截屏（任务计划最小只能 1 分钟）。清除设置即停。"""
        secs = config.SETTINGS.get("test_interval_seconds")
        _logger.info("测试模式：每 %s 秒截屏一次（设置页改回分钟即退出）", secs)
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

    webview.start(debug=False)


if __name__ == "__main__":
    if "--capture" in sys.argv:
        sys.exit(capture.main())
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
