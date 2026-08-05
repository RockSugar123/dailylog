/* dailylog 桌面应用前端：模块化页面（时间线 / 日报周报 / 设置），暗色玻璃风格。 */
"use strict";

/* ===================== 数据层 ===================== */

/* 浏览器调试兜底数据（仅在没有 pywebview 桥时使用） */
const MOCK_RECORDS = [
  { ts: "2026-07-31T14:35:00", activity: "writing", label: "文档", summary: "撰写数据看板需求文档", detail: "核对埋点字段定义", progress: "完成初稿", todo: "", apps: [], contains_sensitive: false },
  { ts: "2026-07-31T10:22:00", activity: "communication", label: "沟通", summary: "确认 iOS 原型需求方向，输出任务清单", detail: "", progress: "", todo: "排期评审", apps: [], contains_sensitive: false },
  { ts: "2026-07-31T09:10:00", activity: "coding", label: "开发", summary: "修复登录接口 token 过期处理 bug", detail: "涉及认证模块和请求拦截逻辑（VS Code）", progress: "本地验证通过，待提交", todo: "补充超时重试的单元测试", apps: ["VS Code"], contains_sensitive: false },
];

/* pywebview 的桥在页面加载完成（NavigationCompleted）后才注入，
 * 必须等 pywebviewready 事件，不能在一加载时就捕获。 */
let bridgeReady = false;
window.addEventListener("pywebviewready", () => {
  bridgeReady = true;
  loadTimeline();
  loadSettings();
  if (!document.getElementById("page-reports").hidden) loadReports();
});

function getApi() {
  if (!bridgeReady && !window.pywebview) return null;
  return window.pywebview?.api || null;
}

async function apiCall(name, ...args) {
  const api = getApi();
  if (!api) return null;
  const fn = api[name];
  if (typeof fn !== "function") {
    console.warn("API 方法不存在:", name);
    return null;
  }
  return await fn(...args);
}

function todayStr() {
  const d = new Date();
  const p = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}
function addDaysStr(dateStr, days) {
  const d = new Date(dateStr + "T12:00:00");
  d.setDate(d.getDate() + days);
  const p = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}
function fmtHM(iso) { return iso ? iso.slice(11, 16) : ""; }
function fmtTime(iso) { return iso ? iso.slice(11, 19) : ""; }
const WEEK = ["周日", "周一", "周二", "周三", "周四", "周五", "周六"];
function dayLabel(dateStr) {
  const d = new Date(dateStr + "T12:00:00");
  return `${dateStr.slice(5).replace("-", "-")} ${WEEK[d.getDay()]}`;
}

/* 分类配色（用户指定） */
const CAT_COLORS = {
  "开发": "#10b981", "会议": "#2563eb", "沟通": "#f59e0b", "文档": "#9333ea",
  "测试": "#ef4444", "设计": "#06b6d4", "运维": "#ef4444", "数据分析": "#14b8a6",
  "学习": "#4f46e5", "管理": "#db2777", "产品": "#9333ea", "生活": "#f97316",
  "其他": "#6b7280",
};
function catColor(label) { return CAT_COLORS[label] || "#6b7280"; }

/* ===================== 通用 UI ===================== */

let toastTimer = null;
function toast(msg, ms = 2600) {
  const el = document.getElementById("toast");
  el.textContent = msg;
  el.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { el.hidden = true; }, ms);
}

const backdrop = document.getElementById("modal-backdrop");
const modalTitle = document.getElementById("modal-title");
const modalBody = document.getElementById("modal-body");
const modalFoot = document.getElementById("modal-foot");

function openModal(title, bodyHtml, footHtml) {
  modalTitle.textContent = title;
  modalBody.innerHTML = bodyHtml;
  if (footHtml) { modalFoot.hidden = false; modalFoot.innerHTML = footHtml; }
  else { modalFoot.hidden = true; modalFoot.innerHTML = ""; }
  backdrop.hidden = false;
}
function closeModal() { backdrop.hidden = true; modalBody.innerHTML = ""; }

document.getElementById("modal-close").addEventListener("click", closeModal);
backdrop.addEventListener("click", (e) => { if (e.target === backdrop) closeModal(); });
document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeModal(); });

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
function mdInline(s) {
  return escapeHtml(s).replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>").replace(/`(.+?)`/g, "<code>$1</code>");
}
function mdToHtml(md) {
  const lines = md.replace(/\r\n/g, "\n").split("\n");
  let html = "", inUl = false, inOl = false, inTable = false, tableRowCount = 0, para = [];
  const flushPara = () => { if (para.length) { html += `<p>${para.map(escapeHtml).join("<br>")}</p>`; para = []; } };
  const closeList = () => { if (inUl) { html += "</ul>"; inUl = false; } if (inOl) { html += "</ol>"; inOl = false; } };
  const closeTable = () => { if (inTable) { html += "</table>"; inTable = false; } };
  for (const raw of lines) {
    const line = raw.trimEnd();
    if (!line.trim()) { flushPara(); closeList(); continue; }
    const h = line.match(/^(#{1,3})\s+(.*)/);
    if (h) { flushPara(); closeList(); closeTable(); html += `<h${h[1].length}>${escapeHtml(h[2])}</h${h[1].length}>`; continue; }
    const ul = line.match(/^\s*[-*]\s+(.*)/);
    if (ul) { flushPara(); if (!inUl) { html += "<ul>"; inUl = true; } html += `<li>${mdInline(ul[1])}</li>`; continue; }
    const ol = line.match(/^\s*\d+[.)]\s+(.*)/);
    if (ol) { flushPara(); if (!inOl) { html += "<ol>"; inOl = true; } html += `<li>${mdInline(ol[1])}</li>`; continue; }
    if (line.includes("|") && line.trim().startsWith("|")) {
      closeList(); flushPara();
      const cells = line.split("|").slice(1, -1).map((c) => c.trim());
      if (!inTable) { html += "<table>"; inTable = true; tableRowCount = 0; }
      if (cells.every((c) => /^:?-{2,}:?$/.test(c))) continue;
      const tag = tableRowCount === 0 ? "th" : "td";
      html += `<tr>${cells.map((c) => `<${tag}>${mdInline(c)}</${tag}>`).join("")}</tr>`;
      tableRowCount++;
      continue;
    }
    closeList(); para.push(line);
  }
  flushPara(); closeList(); closeTable();
  return html;
}

/* ===================== 窗口控制（无边框：手动拖拽 + 缩放） ===================== */

function bindWindowDrag() {
  const titlebar = document.getElementById("titlebar");
  let drag = null;
  titlebar.addEventListener("mousedown", (e) => {
    if (e.target.closest(".tb-btn") || e.target.closest(".tb-rec")) return; // 按钮/开关不参与拖拽
    drag = { offX: e.screenX - window.screenX, offY: e.screenY - window.screenY };
    e.preventDefault();
  });
  window.addEventListener("mousemove", (e) => {
    if (drag) apiCall("move", e.screenX - drag.offX, e.screenY - drag.offY);
  });
  window.addEventListener("mouseup", () => { drag = null; });
}

function bindResizeGrip() {
  const grip = document.getElementById("resize-grip");
  let res = null;
  grip.addEventListener("mousedown", (e) => {
    res = { w: window.innerWidth, h: window.innerHeight, sx: e.screenX, sy: e.screenY };
    e.preventDefault();
    e.stopPropagation();
  });
  window.addEventListener("mousemove", (e) => {
    if (res) apiCall("resize", res.w + (e.screenX - res.sx), res.h + (e.screenY - res.sy));
  });
  window.addEventListener("mouseup", () => { res = null; });
}

document.getElementById("win-min").addEventListener("click", () => apiCall("minimize"));
document.getElementById("win-max").addEventListener("click", () => apiCall("maximize"));
document.getElementById("win-close").addEventListener("click", () => apiCall("close_window"));

/* ===================== 页面切换 ===================== */

const PAGES = { timeline: "page-timeline", todos: "page-todos", reports: "page-reports", logs: "page-logs", settings: "page-settings" };

document.querySelectorAll(".side-item[data-page]").forEach((item) => {
  item.addEventListener("click", () => switchPage(item.dataset.page));
});
function switchPage(name) {
  document.querySelectorAll(".side-item[data-page]").forEach((i) => i.classList.toggle("active", i.dataset.page === name));
  Object.entries(PAGES).forEach(([key, id]) => { document.getElementById(id).hidden = key !== name; });
  if (name === "todos") loadTodos();
  if (name === "reports") loadReports();
  if (name === "logs") loadLogs();
  if (name === "settings") loadSettings();
}

/* ===================== 日志页 ===================== */

async function loadLogs() {
  const r = await apiCall("get_logs");
  const el = document.getElementById("logs-list");
  const count = document.getElementById("logs-count");
  if (!r || !r.ok) {
    el.innerHTML = `<div class="logs-empty">读取失败：${escapeHtml(r ? r.error : "无响应")}</div>`;
    count.textContent = "";
    return;
  }
  if (!r.logs.length) {
    el.innerHTML = '<div class="logs-empty">暂无日志</div>';
    count.textContent = "";
    return;
  }
  count.textContent = `共 ${r.logs.length} 条`;
  el.innerHTML = r.logs.map((l) => {
    const cls = l.level === "ERROR" ? " log-err" : l.level === "WARNING" ? " log-warn" : "";
    return `<div class="log-line${cls}"><span class="log-ts">${escapeHtml(l.ts)}</span><span class="log-lv">${escapeHtml(l.level)}</span><span class="log-msg">${escapeHtml(l.msg)}</span></div>`;
  }).join("");
}
document.getElementById("logs-refresh").addEventListener("click", loadLogs);

/* ===================== 时间线页 ===================== */

let rangeStart = todayStr();
let rangeEnd = todayStr();
let timelineRecords = [];
let lastTimelineSig = "";

function applyRange(start, end) {
  rangeStart = start;
  rangeEnd = end;
  document.getElementById("range-start").value = start;
  document.getElementById("range-end").value = end;
  loadTimeline();
}

async function loadTimeline() {
  const records = (await apiCall("get_records_range", rangeStart, rangeEnd)) || MOCK_RECORDS;
  timelineRecords = records.slice().sort((a, b) => (a.ts || "").localeCompare(b.ts || ""));
  lastTimelineSig = sigOf(timelineRecords);
  renderStats();
  renderCats();
  renderTimeline();
}

function sigOf(records) {
  return records.length + "|" + (records.length ? records[records.length - 1].ts : "");
}

// 定时截屏产生新记录时自动刷新时间线（差异检测，避免无谓重渲染）
async function refreshTimelineIfChanged() {
  const records = await apiCall("get_records_range", rangeStart, rangeEnd);
  if (!records || sigOf(records) === lastTimelineSig) return;
  loadTimeline();
}

function recordDuration(records, i) {
  // 该条记录估测时长：与下一条间隔（截断到 1~60 分钟），最后一条按当前设置间隔估算
  if (i < records.length - 1) {
    const gap = (new Date(records[i + 1].ts) - new Date(records[i].ts)) / 60000;
    return Math.max(1, Math.min(60, gap));
  }
  return currentInterval || 10;
}

function renderStats() {
  const n = timelineRecords.length;
  document.getElementById("st-count").textContent = n;
  const el = document.getElementById("st-range");
  const focus = document.getElementById("st-focus");
  if (!n) { el.textContent = "–"; focus.textContent = "–"; return; }
  el.textContent = `${fmtHM(timelineRecords[0].ts)} — ${fmtHM(timelineRecords[n - 1].ts)}`;
  const totalMin = timelineRecords.reduce((sum, _, i) => sum + recordDuration(timelineRecords, i), 0);
  focus.textContent = totalMin >= 60 ? `${Math.floor(totalMin / 60)}h` : `${Math.floor(totalMin)}m`;
}

function renderCats() {
  const panel = document.getElementById("panel-cats");
  const list = document.getElementById("cat-list");
  if (!timelineRecords.length) { panel.hidden = true; return; }
  const byCat = {};
  timelineRecords.forEach((r, i) => {
    const label = r.label || "其他";
    const dur = recordDuration(timelineRecords, i);
    byCat[label] = (byCat[label] || 0) + dur;
  });
  const total = Object.values(byCat).reduce((a, b) => a + b, 0);
  list.innerHTML = Object.entries(byCat)
    .sort((a, b) => b[1] - a[1])
    .map(([label, min]) => `
      <div class="cat-item">
        <span class="cat-label">${escapeHtml(label)}</span>
        <div class="cat-bar"><div class="cat-fill" style="width:${(min / total * 100).toFixed(1)}%;background:${catColor(label)}"></div></div>
        <span class="cat-value">${min >= 60 ? Math.floor(min / 60) + "h" : Math.floor(min) + "m"}</span>
      </div>`).join("");
  panel.hidden = false;
}

function renderTimeline() {
  const box = document.getElementById("timeline");
  const desc = document.getElementById("tl-desc").checked;
  document.getElementById("tl-count").textContent = timelineRecords.length ? `${timelineRecords.length} 条` : "";
  if (!timelineRecords.length) {
    box.innerHTML = `<div class="tl-empty">这个时间段还没有记录。<br>放轻松，自动记录会替你补上接下来的每一分钟。</div>`;
    return;
  }
  // 按天分组，日期降序（最新在前）；天内按开关决定顺序
  const groups = new Map();
  timelineRecords.forEach((r) => {
    const day = r.ts.slice(0, 10);
    if (!groups.has(day)) groups.set(day, []);
    groups.get(day).push(r);
  });
  const days = [...groups.keys()].sort().reverse();
  let html = "";
  for (const day of days) {
    const items = groups.get(day);
    const ordered = desc ? [...items].reverse() : items;
    html += `<div class="tl-day">${dayLabel(day)}<em>${items.length} 条</em></div>`;
    html += ordered.map((r) => {
      const color = catColor(r.label);
      return `
      <div class="tl-item">
        <div class="tl-time">${fmtTime(r.ts)}</div>
        <div class="tl-dot" style="background:${color};box-shadow:0 0 0 2px ${color}33,0 0 12px ${color}88"></div>
        <div class="tl-content" data-ts="${escapeHtml(r.ts || "")}">
          <div class="tl-text">${escapeHtml(r.summary || "")}</div>
          ${r.detail ? `<div class="tl-detail">${escapeHtml(r.detail)}</div>` : ""}
          <div class="tl-foot">
            <span class="tl-tag" style="background:${color}24;color:${color}">${escapeHtml(r.label || "其他")}</span>
            ${r.todo ? `<span class="tl-todo">待办：${escapeHtml(r.todo.slice(0, 24))}</span>` : ""}
          </div>
        </div>
      </div>`;
    }).join("");
  }
  box.innerHTML = html;
  box.querySelectorAll(".tl-content").forEach((el) => {
    el.addEventListener("click", () => {
      const rec = timelineRecords.find((r) => r.ts === el.dataset.ts);
      if (rec) openRecordModal(rec);
    });
  });
}

function openRecordModal(rec) {
  const block = (label, value) => value
    ? `<div class="rec-block"><strong>${label}</strong><p>${escapeHtml(value)}</p></div>` : "";
  openModal(
    "时间线记录",
    `<div style="font-size:12px;color:var(--faint)">${escapeHtml(rec.ts || "")}</div>
     <span class="rec-label" style="background:${catColor(rec.label)}24;color:${catColor(rec.label)}">${escapeHtml(rec.label || "其他")}</span>
     <p style="font-weight:600;margin:4px 0 0">${escapeHtml(rec.summary || "")}</p>
     ${block("详情", rec.detail)}${block("进展", rec.progress)}${block("待办", rec.todo)}
     ${rec.apps && rec.apps.length ? block("涉及应用", rec.apps.join("、")) : ""}
     ${rec.contains_sensitive ? '<div class="rec-block"><strong>敏感标记</strong><p>本条涉及敏感内容，已脱敏</p></div>' : ""}`,
  );
}

/* ===================== 日报周报页 ===================== */

async function generateReport(kind) {
  toast(kind === "day" ? "正在生成日报…" : "正在生成周报…");
  const r = await apiCall("generate_report", kind, "");
  if (!r) { toast("未连接到后端"); return; }
  if (!r.ok) { toast(r.error); return; }
  openModal(kind === "day" ? "今日日报" : "本周周报", `<div class="md-body">${mdToHtml(r.content)}</div>`, `保存位置：${escapeHtml(r.path)}`);
  loadReports();
}

async function loadReports() {
  const list = document.getElementById("report-list");
  const items = (await apiCall("list_reports")) || [];
  document.getElementById("report-count").textContent = items.length ? `${items.length} 份` : "";
  if (!items.length) {
    list.innerHTML = `<div class="report-empty">还没有生成过报告。<br>点上面的按钮，用今天的轨迹写第一份日报。</div>`;
    return;
  }
  list.innerHTML = items.map((x) => `
    <div class="report-item" data-name="${escapeHtml(x.name)}">
      <span class="report-name">${escapeHtml(x.name)}</span>
      <span class="report-mtime">${escapeHtml(x.mtime)}</span>
    </div>`).join("");
  list.querySelectorAll(".report-item").forEach((el) => {
    el.addEventListener("click", async () => {
      const r = await apiCall("get_report", el.dataset.name);
      if (r && r.ok) openModal(r.name, `<div class="md-body">${mdToHtml(r.content)}</div>`);
      else toast((r && r.error) || "读取失败");
    });
  });
}

/* ===================== 设置页 ===================== */

let currentInterval = 10;
let currentIdleMin = 5;
let idleEnabled = true;
let currentRetention = 0;
let dedupEnabled = true;
let enterEnabled = false;
let currentEnterInterval = 15;

function statusHtml(cfg) {
  const next = cfg.recording_enabled
    ? (cfg.test_interval_seconds ? `测试每 ${cfg.test_interval_seconds}s` : (cfg.next_capture || "—"))
    : "已停用";
  return `
    <dt>定时记录</dt><dd class="${cfg.recording_enabled ? "ok" : "bad"}">${cfg.recording_enabled ? "运行中" : "已停用"}</dd>
    <dt>下次截屏</dt><dd>${next}</dd>
    <dt>空闲暂停</dt><dd>${cfg.idle_enabled ? `静止 ${cfg.idle_minutes} 分钟暂停` : "关闭"}</dd>
    <dt>分析模型</dt><dd>${escapeHtml(cfg.analyze_model || "未配置")}</dd>
    <dt>总结模型</dt><dd>${escapeHtml(cfg.summary_model || "未配置")}</dd>
    <dt>API Key</dt><dd>${cfg.has_analyze_key && cfg.has_summary_key ? "均已配置" : (cfg.has_analyze_key ? "分析已配，总结未配" : "分析未配")}</dd>`;
}

function updateStatus(cfg) {
  // 标题栏记录总开关（椭圆开关 + 状态文字，颜色由 .on 类驱动）
  const tb = document.getElementById("rec-toggle");
  tb.classList.toggle("on", !!cfg.recording_enabled);
  tb.setAttribute("aria-pressed", cfg.recording_enabled ? "true" : "false");
  document.getElementById("rec-label-tb").textContent = cfg.recording_enabled ? "记录中" : "已停止";
  // 侧边栏状态（测试模式显示秒级）
  document.getElementById("rec-dot").classList.toggle("off", !cfg.recording_enabled);
  document.getElementById("side-next").textContent = cfg.recording_enabled
    ? (cfg.test_interval_seconds ? `测试每 ${cfg.test_interval_seconds}s` : (cfg.next_capture ? "下次 " + cfg.next_capture : ""))
    : "已停用";
  if (!document.getElementById("page-settings").hidden) {
    document.getElementById("settings-status").innerHTML = statusHtml(cfg);
  }
}

async function loadSettings() {
  const cfg = (await apiCall("get_config")) || {
    interval_minutes: 10, interval_choices: [5, 10, 15, 30, 60], recording_enabled: true,
  };
  currentInterval = cfg.interval_minutes || 10;
  setupSelect("interval-pop", "interval-btn", cfg.interval_choices || [5, 10, 15, 30, 60],
    (m) => `每 ${m} 分钟`, (v) => { currentInterval = Number(v); }, currentInterval);
  idleEnabled = cfg.idle_enabled !== false;
  currentIdleMin = cfg.idle_minutes || 5;
  setupSelect("idle-pop", "idle-btn", cfg.idle_choices || [1, 2, 5, 10, 15, 20, 30],
    (m) => `${m} 分钟`, (v) => { currentIdleMin = Number(v); }, currentIdleMin);
  document.getElementById("idle-enabled").checked = idleEnabled;
  document.getElementById("idle-btn").disabled = !idleEnabled;
  document.getElementById("idle-wrap").style.opacity = idleEnabled ? "1" : "0.45";
  document.getElementById("set-name").value = cfg.report_name || "";
  currentRetention = cfg.retention_days || 0;
  setupSelect("retention-pop", "retention-btn", cfg.retention_choices || [0, 7, 14, 30, 60, 90],
    (d) => (Number(d) === 0 ? "永久保留" : `保留 ${Number(d)} 天`), (v) => { currentRetention = Number(v); }, currentRetention);
  dedupEnabled = cfg.dedup_enabled !== false;
  document.getElementById("dedup-enabled").checked = dedupEnabled;
  enterEnabled = !!cfg.enter_capture_enabled;
  currentEnterInterval = cfg.enter_capture_interval || 15;
  setupSelect("enter-pop", "enter-btn", cfg.enter_interval_choices || [5, 15, 30, 60],
    (s) => `${s} 秒`, (v) => { currentEnterInterval = Number(v); }, currentEnterInterval);
  document.getElementById("enter-enabled").checked = enterEnabled;
  document.getElementById("enter-btn").disabled = !enterEnabled;
  document.getElementById("enter-wrap").style.opacity = enterEnabled ? "1" : "0.45";
  updateStatus(cfg);
  loadDbStats();
}

// 供 Python（托盘开关/启动）调用：刷新定时记录状态与下次截屏时间
let refreshTimer = null;
function scheduleRefresh(ms) {
  if (refreshTimer) clearInterval(refreshTimer);
  refreshTimer = setInterval(() => { refreshStatus(); refreshTimelineIfChanged(); }, ms);
}
async function refreshStatus() {
  const cfg = await apiCall("get_config");
  if (!cfg) return;
  const wantFast = !!cfg.test_interval_seconds;
  const isFast = refreshTimer && refreshTimer._fast === true;
  if (wantFast && !isFast) { scheduleRefresh(10000); refreshTimer._fast = true; }
  else if (!wantFast && isFast) { scheduleRefresh(60000); refreshTimer._fast = false; }
  updateStatus(cfg);
  if (!document.getElementById("page-logs").hidden) loadLogs();  // 日志页可见时跟随刷新
}
scheduleRefresh(60000);

/* 自定义下拉（原生 select 弹出层白底不可控）。值不自动转数字：字符串值（如待办状态）
   原样传给 onPick，数字值的调用方自行 Number() 转换。 */
function setupSelect(popId, btnId, choices, labelFn, onPick, current) {
  const pop = document.getElementById(popId);
  const btn = document.getElementById(btnId);
  pop.innerHTML = choices.map((v) => `<button class="select-opt" data-v="${v}">${labelFn(v)}</button>`).join("");
  pop.querySelectorAll(".select-opt").forEach((opt) => {
    opt.addEventListener("click", (e) => {
      e.stopPropagation();
      btn.dataset.v = opt.dataset.v;
      onPick(opt.dataset.v);
      btn.innerHTML = `${labelFn(opt.dataset.v)}<span class="caret">▾</span>`;
      pop.hidden = true;
    });
  });
  if (!btn.dataset.bound) {
    btn.addEventListener("click", (e) => { e.stopPropagation(); pop.hidden = !pop.hidden; });
    btn.dataset.bound = "1";
  }
  btn.dataset.v = String(current ?? choices[0]);
  btn.innerHTML = `${labelFn(btn.dataset.v)}<span class="caret">▾</span>`;
}

document.addEventListener("click", () => {
  document.querySelectorAll(".select-pop").forEach((p) => { p.hidden = true; });
});

/* 手动截屏：设置页按钮触发，5 秒倒计时后调后端（防重入）。
   倒计时期间窗口可见，用户可切走；后端截屏时会自动隐藏本窗口再恢复。 */
let manualTimer = null;
function startManualCapture() {
  if (manualTimer) return;
  let n = 5;
  toast("5 秒后截取当前屏幕，可先切换窗口…");
  manualTimer = setInterval(async () => {
    n--;
    if (n <= 0) {
      clearInterval(manualTimer);
      manualTimer = null;
      toast("正在分析屏幕…（约 10-60 秒）", 0); // 持久显示，完成后再替换
      const r = await apiCall("manual_capture");
      toast(r && r.ok ? "已记录本次截屏" : "记录失败，详见 dailylog.log", r && r.ok ? 2600 : 6000);
      refreshStatus();
    } else {
      toast(`${n} 秒后截取当前屏幕…`);
    }
  }, 1000);
}
document.getElementById("manual-capture").addEventListener("click", startManualCapture);

document.getElementById("idle-enabled").addEventListener("change", (e) => {
  idleEnabled = e.target.checked;
  document.getElementById("idle-btn").disabled = !idleEnabled;
  document.getElementById("idle-wrap").style.opacity = idleEnabled ? "1" : "0.45";
});
document.getElementById("enter-enabled").addEventListener("change", (e) => {
  enterEnabled = e.target.checked;
  document.getElementById("enter-btn").disabled = !enterEnabled;
  document.getElementById("enter-wrap").style.opacity = enterEnabled ? "1" : "0.45";
});

/* ===================== 待办页 ===================== */

let todoItems = [];
let todoStatusFilter = "全部状态";
let todoPriorityFilter = "全部优先级";
let todoSearch = "";

const TODO_STATUSES = ["未开始", "进行中", "已完成", "归档"];
const PRIO_COLORS = { "高": "#ef4444", "中": "#f59e0b", "低": "#6b7280" };

async function loadTodos() {
  todoItems = (await apiCall("get_todos")) || [];
  renderTodos();
}

function renderTodos() {
  const kw = todoSearch.trim();
  const filtered = todoItems.filter((it) =>
    (todoStatusFilter === "全部状态" || it.status === todoStatusFilter) &&
    (todoPriorityFilter === "全部优先级" || it.priority === todoPriorityFilter) &&
    (!kw || it.text.includes(kw)));
  const el = document.getElementById("todo-list");
  document.getElementById("todo-count").textContent = filtered.length ? `${filtered.length} 条` : "";
  if (!filtered.length) {
    el.innerHTML = `<div class="tl-empty">没有匹配的待办。</div>`;
    return;
  }
  el.innerHTML = filtered.map((it) => {
    const done = it.status === "已完成";
    const pc = PRIO_COLORS[it.priority] || "#6b7280";
    const ai = it.source === "ai" ? `<span class="tl-tag" style="background:#2563eb24;color:#2563eb">AI</span>` : "";
    return `
    <div class="todo-item${done ? " done" : ""}" data-id="${escapeHtml(it.id)}">
      <input type="checkbox" class="todo-check" ${done ? "checked" : ""} title="标记完成/未完成" />
      <span class="todo-text">${mdInline(it.text)}</span>
      ${ai}
      <span class="tl-tag" style="background:${pc}24;color:${pc}">${escapeHtml(it.priority)}</span>
      <select class="todo-status-sel" title="切换状态">
        ${TODO_STATUSES.map((s) => `<option ${s === it.status ? "selected" : ""}>${s}</option>`).join("")}
      </select>
      <span class="todo-ts hint">${escapeHtml((it.ts || "").slice(0, 10))}</span>
      <button class="todo-del" title="删除">✕</button>
    </div>`;
  }).join("");
  el.querySelectorAll(".todo-item").forEach((row) => {
    const id = row.dataset.id;
    row.querySelector(".todo-check").addEventListener("change", async (e) => {
      const r = await apiCall("set_todo_status", id, e.target.checked ? "已完成" : "未开始");
      if (r && r.ok) loadTodos(); else toast((r && r.error) || "更新失败");
    });
    row.querySelector(".todo-status-sel").addEventListener("change", async (e) => {
      const r = await apiCall("set_todo_status", id, e.target.value);
      if (r && r.ok) loadTodos(); else toast((r && r.error) || "更新失败");
    });
    row.querySelector(".todo-del").addEventListener("click", async () => {
      const r = await apiCall("delete_todo", id);
      toast(r && r.ok ? "已删除" : ((r && r.error) || "删除失败"));
      if (r && r.ok) loadTodos();
    });
  });
}

/* 状态/优先级筛选 + 搜索（全在前端过滤，数据量小） */
setupSelect("todo-status-pop", "todo-status-btn", ["全部状态", ...TODO_STATUSES],
  (v) => v, (v) => { todoStatusFilter = v; renderTodos(); }, "全部状态");
setupSelect("todo-priority-pop", "todo-priority-btn", ["全部优先级", "高", "中", "低"],
  (v) => v, (v) => { todoPriorityFilter = v; renderTodos(); }, "全部优先级");
document.getElementById("todo-search").addEventListener("input", (e) => {
  todoSearch = e.target.value;
  renderTodos();
});

/* 新建待办弹窗：内容输入 + 优先级选择 */
document.getElementById("todo-add").addEventListener("click", () => {
  const prioBtns = ["高", "中", "低"].map((p) => `<button class="prio-opt${p === "中" ? " sel" : ""}" data-p="${p}">${p}</button>`).join("");
  openModal("新建待办",
    `<input type="text" id="todo-new-text" maxlength="100" placeholder="要做什么？" class="modal-input" />
     <div style="margin-top:12px"><span class="hint">优先级</span>
       <div class="prio-pick">${prioBtns}</div>
     </div>`,
    `<button class="btn-primary" id="todo-new-ok">添加</button>`);
  let prio = "中";
  document.querySelectorAll(".prio-opt").forEach((b) => {
    b.addEventListener("click", () => {
      prio = b.dataset.p;
      document.querySelectorAll(".prio-opt").forEach((x) => x.classList.remove("sel"));
      b.classList.add("sel");
    });
  });
  const doAdd = async () => {
    const text = document.getElementById("todo-new-text").value.trim();
    if (!text) { toast("待办内容不能为空"); return; }
    const r = await apiCall("add_todo", text, prio);
    if (r && r.ok) { toast("已添加待办"); closeModal(); loadTodos(); }
    else toast((r && r.error) || "添加失败");
  };
  document.getElementById("todo-new-ok").addEventListener("click", doAdd);
  document.getElementById("todo-new-text").addEventListener("keydown", (e) => { if (e.key === "Enter") doAdd(); });
  document.getElementById("todo-new-text").focus();
});

/* ===================== 数据管理 ===================== */

async function loadDbStats() {
  const s = await apiCall("db_stats");
  if (!s) return;
  const vals = document.querySelectorAll("#db-stats .db-value");
  if (vals.length === 4) {
    vals[0].textContent = s.size_mb >= 1 ? `${s.size_mb} MB` : `${s.size_kb} KB`;
    vals[1].textContent = s.timeline_count;
    vals[2].textContent = s.report_count;
    vals[3].textContent = s.log_count;
  }
}

document.getElementById("export-data").addEventListener("click", async () => {
  const r = await apiCall("export_data_dialog");
  if (!r) { toast("未连接到后端"); return; }
  if (r.ok) toast(`已导出到 ${r.path}`);
  else if (!r.cancelled) toast(r.error || "导出失败");
});

document.getElementById("import-data").addEventListener("click", async () => {
  const r = await apiCall("import_data_dialog");
  if (!r) { toast("未连接到后端"); return; }
  if (r.ok) {
    toast(`导入完成：记录 ${r.records} 天、报告 ${r.reports} 份`);
    loadDbStats();
  } else if (!r.cancelled) toast(r.error || "导入失败");
});

document.getElementById("clear-data").addEventListener("click", () => {
  openModal("清除历史数据",
    `<p style="color:var(--danger,#ef4444);margin:0 0 8px">将删除：时间线记录（jsonl + md）、生成的报告、本地日志、待办列表。</p>
     <p class="hint" style="margin:0">保留：API Key 配置（.env）与设置。</p>`,
    `<button class="btn-danger" id="clear-ok">确认删除</button>`);
  document.getElementById("clear-ok").addEventListener("click", async () => {
    const r = await apiCall("clear_data");
    closeModal();
    toast(r && r.ok ? `已清除 ${r.records} 条记录、${r.reports} 份报告` : ((r && r.error) || "清除失败"));
    if (r && r.ok) loadDbStats();
  });
});

document.getElementById("set-save").addEventListener("click", async () => {
  const ri = await apiCall("set_interval", currentInterval);
  const name = document.getElementById("set-name").value.trim();
  const rn = await apiCall("set_report_name", name);
  const rd = await apiCall("set_idle", idleEnabled, currentIdleMin);
  const rr = await apiCall("set_retention", currentRetention);
  const rdu = await apiCall("set_dedup", dedupEnabled);
  const re = await apiCall("set_enter_capture", enterEnabled, currentEnterInterval);
  const results = [ri, rn, rd, rr, rdu, re];
  const firstErr = results.find((r) => r && !r.ok);
  if (results.every((r) => r && r.ok)) {
    toast(`已保存：间隔每 ${ri.interval_minutes} 分钟，空闲${idleEnabled ? currentIdleMin + " 分钟暂停" : "暂停关闭"}，记录${currentRetention ? "保留 " + currentRetention + " 天" : "永久保留"}，去重${dedupEnabled ? "开" : "关"}，回车${enterEnabled ? "开" : "关"}${name ? "，汇报人 " + name : ""}`);
  } else {
    toast((firstErr && firstErr.error) || "保存失败（浏览器预览不可用）");
  }
  loadSettings();
});

/* 标题栏记录总开关 */
document.getElementById("rec-toggle").addEventListener("click", async () => {
  const r = await apiCall("toggle_recording");
  if (r && r.ok) { toast(r.recording_enabled ? "定时记录已开始" : "定时记录已停止"); refreshStatus(); }
  else toast((r && r.error) || "切换失败");
});

/* ===================== 隐私 / 关于 ===================== */

document.getElementById("side-privacy").addEventListener("click", () => {
  openModal("隐私保护",
    `<p>1. <b>即用即删</b>：截屏只在分析瞬间存在，分析完立即删除，磁盘不保留原始画面。</p>
     <p>2. <b>输出脱敏</b>：分析模型被要求不输出密码、密钥、验证码、联系人身份、私人聊天内容等，只用占位符概括。</p>
     <p>3. <b>边界说明</b>：截屏明文会上传 NVIDIA NIM 服务端，脱敏规则只约束"输出"，不约束"输入"。</p>
     <p>4. 时间线记录仅保存在本机 dailylog 目录。</p>`);
});
document.getElementById("side-about").addEventListener("click", () => {
  openModal("关于",
    `<p><b>dailylog · 今日轨迹</b></p>
     <p>每 10 分钟自动截屏分析，把一天的工作记录成时间线，一键生成日报周报。</p>
     <p style="color:var(--faint);font-size:12px">截图分析：minimaxai/minimax-m3（NVIDIA NIM）<br>日报周报：deepseek-v4-flash（DeepSeek）</p>`);
});

/* ===================== 事件绑定 ===================== */

document.getElementById("range-start").addEventListener("change", (e) => {
  if (e.target.value) applyRange(e.target.value, rangeEnd < e.target.value ? e.target.value : rangeEnd);
});
document.getElementById("range-end").addEventListener("change", (e) => {
  if (e.target.value) applyRange(rangeStart > e.target.value ? e.target.value : rangeStart, e.target.value);
});
document.querySelectorAll(".preset").forEach((btn) => {
  btn.addEventListener("click", () => {
    const days = Number(btn.dataset.days);
    applyRange(addDaysStr(todayStr(), -(days - 1)), todayStr());
  });
});
document.getElementById("tl-desc").addEventListener("change", renderTimeline);
document.getElementById("gen-day").addEventListener("click", () => generateReport("day"));
document.getElementById("gen-week").addEventListener("click", () => generateReport("week"));

/* ===================== 启动 ===================== */

applyRange(todayStr(), todayStr());
bindWindowDrag();
bindResizeGrip();
