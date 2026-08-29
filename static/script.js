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
  loadHome();
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

/* ===================== 皮肤（glass=玻璃拟态 / paper=纸面编辑部 / journal=暖光手账 /
 * terminal=墨绿终端 / abyss=深海蓝调 / film=胶片暗房 / mint=薄荷汽水 / sakura=樱吹雪） ===================== */

const THEMES = {
  glass: "玻璃拟态", paper: "纸面编辑部", journal: "暖光手账",
  terminal: "墨绿终端", abyss: "深海蓝调", film: "胶片暗房",
  mint: "薄荷汽水", sakura: "樱吹雪",
};
function applyTheme(theme) {
  for (const key of Object.keys(THEMES)) {
    if (key !== "glass") document.body.classList.toggle("theme-" + key, theme === key);
  }
  FX.setTheme(theme);
  try { localStorage.setItem("dailylog-theme", theme); } catch (_) { /* 隐私模式等场景下不可写，忽略 */ }
}

/* 统一特效引擎：按皮肤渲染常驻环境粒子 + 鼠标点击迸发特效。
 * 画布 z-index 95（内容之上、弹窗之下），pointer-events 穿透；
 * prefers-reduced-motion 下整体禁用。 */
const FX = (() => {
  let cv = null, ctx = null, rafId = 0, parts = [], bursts = [], theme = "glass", running = false;
  const GLYPHS = "01<>/#$;:";
  const PINKS = [[255, 183, 197], [255, 205, 220], [250, 160, 185], [255, 225, 232], [244, 143, 177]];
  const PASTELS = ["255,154,108", "168,213,186", "245,227,163", "125,200,235", "242,136,171"];
  const EMBERS = ["255,140,80", "255,90,90", "255,180,120"];
  /* 各皮肤环境粒子数量（sakura 按窗口宽度动态收缩） */
  const N = { glass: 14, paper: 6, journal: 10, terminal: 16, abyss: 10, film: 14, mint: 9, sakura: 38 };

  function initPart(w, h, any) {
    if (theme === "sakura") return { x: Math.random() * w, y: any ? Math.random() * h : -20 - Math.random() * h * .25, s: 5 + Math.random() * 6, vy: .45 + Math.random() * 1.05, sw: .6 + Math.random() * 1.6, ph: Math.random() * 6.28, rot: Math.random() * 6.28, vr: (Math.random() - .5) * .05, c: PINKS[(Math.random() * PINKS.length) | 0], o: .5 + Math.random() * .35 };
    if (theme === "glass") return { x: Math.random() * w, y: any ? Math.random() * h : h + 6, vy: .18 + Math.random() * .42, r: .8 + Math.random() * 1.6, ph: Math.random() * 6.28, fl: 2 + Math.random() * 3, c: EMBERS[(Math.random() * 3) | 0] };
    if (theme === "paper") return { x: Math.random() * w, y: Math.random() * h, vx: .06 + Math.random() * .12, vy: .04 + Math.random() * .09, r: .8 + Math.random() * .9, a: .04 + Math.random() * .06 };
    if (theme === "journal") return { x: Math.random() * w, y: any ? Math.random() * h : h + 8, vy: .2 + Math.random() * .35, r: 2 + Math.random() * 3, ph: Math.random() * 6.28, c: PASTELS[(Math.random() * PASTELS.length) | 0], a: .12 + Math.random() * .1 };
    if (theme === "terminal") return { x: Math.random() * w, y: any ? Math.random() * h : -12, vy: .25 + Math.random() * .5, ch: GLYPHS[(Math.random() * GLYPHS.length) | 0], a: .14 + Math.random() * .22 };
    if (theme === "abyss") return { x: Math.random() * w, y: any ? Math.random() * h : h + 8, vy: .3 + Math.random() * .5, r: 1.5 + Math.random() * 2.5, ph: Math.random() * 6.28 };
    if (theme === "film") return { x: Math.random() * w, y: any ? Math.random() * h : -6, vy: .12 + Math.random() * .3, r: .8 + Math.random() * 1.8, big: Math.random() < .18, ph: Math.random() * 6.28, a: .05 + Math.random() * .13 };
    return { x: Math.random() * w, y: any ? Math.random() * h : h + 8, vy: .25 + Math.random() * .4, r: 2 + Math.random() * 3, ph: Math.random() * 6.28 }; /* mint */
  }
  function petalPath(s) {
    ctx.beginPath();
    ctx.moveTo(0, -s);
    ctx.bezierCurveTo(s * .85, -s * .45, s * .62, s * .62, 0, s);
    ctx.bezierCurveTo(-s * .62, s * .62, -s * .85, -s * .45, 0, -s);
    ctx.quadraticCurveTo(-s * .18, -s * .55, 0, -s * .72);
    ctx.quadraticCurveTo(s * .18, -s * .55, 0, -s);
    ctx.fill();
  }
  function stepPart(p, w, h) {
    if (theme === "sakura") {
      p.ph += .008 + p.sw * .004; p.x += Math.sin(p.ph) * p.sw * .6; p.y += p.vy; p.rot += p.vr;
      if (p.y > h + 24 || p.x < -40 || p.x > w + 40) Object.assign(p, initPart(w, h, false));
      ctx.save(); ctx.translate(p.x, p.y); ctx.rotate(p.rot + Math.sin(p.ph) * .45);
      ctx.fillStyle = `rgba(${p.c[0]},${p.c[1]},${p.c[2]},${p.o})`;
      petalPath(p.s); ctx.restore();
    } else if (theme === "glass") {
      p.y -= p.vy; p.ph += .02; p.x += Math.sin(p.ph * .7) * .2;
      if (p.y < -8) Object.assign(p, initPart(w, h, false));
      const flick = .5 + .5 * Math.sin(p.ph * p.fl * 6);
      ctx.fillStyle = `rgba(${p.c},${.18 + .4 * flick})`;
      ctx.beginPath(); ctx.arc(p.x, p.y, p.r, 0, 7); ctx.fill();
    } else if (theme === "paper") {
      p.x += p.vx; p.y += p.vy;
      if (p.x > w + 6) p.x = -6;
      if (p.y > h + 6) p.y = -6;
      ctx.fillStyle = `rgba(60,50,40,${p.a})`;
      ctx.beginPath(); ctx.arc(p.x, p.y, p.r, 0, 7); ctx.fill();
    } else if (theme === "journal") {
      p.y -= p.vy; p.x += Math.sin(p.ph += .012) * .35;
      if (p.y < -10) Object.assign(p, initPart(w, h, false));
      ctx.fillStyle = `rgba(${p.c},${p.a})`;
      ctx.beginPath(); ctx.arc(p.x, p.y, p.r, 0, 7); ctx.fill();
    } else if (theme === "terminal") {
      p.y += p.vy;
      if (p.y > h + 12) Object.assign(p, initPart(w, h, false));
      ctx.fillStyle = `rgba(102,220,150,${p.a})`; ctx.font = "10px Consolas,monospace"; ctx.fillText(p.ch, p.x, p.y);
    } else if (theme === "abyss") {
      p.y -= p.vy; p.x += Math.sin(p.ph += .01) * .3;
      if (p.y < -10) Object.assign(p, initPart(w, h, false));
      ctx.strokeStyle = "rgba(140,200,255,.38)"; ctx.lineWidth = 1;
      ctx.beginPath(); ctx.arc(p.x, p.y, p.r, 0, 7); ctx.stroke();
    } else if (theme === "film") {
      p.y += p.vy; p.x += Math.sin(p.ph += .006) * .2;
      if (p.y > h + 8) Object.assign(p, initPart(w, h, false));
      ctx.fillStyle = `rgba(255,225,180,${p.big ? .05 : p.a})`;
      ctx.beginPath(); ctx.arc(p.x, p.y, p.big ? p.r * 3 : p.r, 0, 7); ctx.fill();
    } else { /* mint */
      p.y -= p.vy; p.x += Math.sin(p.ph += .012) * .35;
      if (p.y < -10) Object.assign(p, initPart(w, h, false));
      ctx.fillStyle = "rgba(23,199,143,.28)";
      ctx.beginPath(); ctx.arc(p.x, p.y, p.r, 0, 7); ctx.fill();
    }
  }
  function drawBurst(x, y, t) {
    const f = 1 - t;
    if (theme === "terminal") {
      const s1 = 12 + t * 36;
      ctx.strokeStyle = `rgba(66,217,140,${f})`; ctx.lineWidth = 1.5;
      ctx.strokeRect(x - s1, y - s1, s1 * 2, s1 * 2);
      const s2 = 6 + Math.max(0, t - .18) * 44;
      ctx.strokeStyle = `rgba(66,217,140,${f * .6})`;
      ctx.strokeRect(x - s2, y - s2, s2 * 2, s2 * 2);
      ctx.fillStyle = `rgba(130,240,180,${f})`;
      for (let i = 0; i < 6; i++) { const a = i * Math.PI / 3 + .4; ctx.fillRect(x + Math.cos(a) * t * 34 - 1.5, y + Math.sin(a) * t * 34 - 1.5, 3, 3); }
    } else if (theme === "abyss") {
      for (let i = 0; i < 3; i++) {
        ctx.strokeStyle = `rgba(120,200,255,${f * (.85 - i * .22)})`; ctx.lineWidth = 1.6 - i * .4;
        ctx.beginPath(); ctx.arc(x, y, 5 + i * 8 + t * (40 + i * 16), 0, 7); ctx.stroke();
      }
    } else if (theme === "film") {
      const g = ctx.createRadialGradient(x, y, 0, x, y, 20 + t * 56);
      g.addColorStop(0, `rgba(255,214,160,${f * .3})`); g.addColorStop(1, "rgba(255,214,160,0)");
      ctx.fillStyle = g; ctx.beginPath(); ctx.arc(x, y, 20 + t * 56, 0, 7); ctx.fill();
      ctx.fillStyle = `rgba(255,200,140,${f * .55})`;
      for (let i = 0; i < 6; i++) { const a = i * Math.PI / 3 + .8; ctx.beginPath(); ctx.arc(x + Math.cos(a) * t * 40, y + Math.sin(a) * t * 40, 2.4, 0, 7); ctx.fill(); }
    } else if (theme === "mint") {
      ctx.strokeStyle = `rgba(14,170,125,${f})`; ctx.lineWidth = 1.6;
      ctx.beginPath(); ctx.arc(x, y, 4 + t * 30, 0, 7); ctx.stroke();
      ctx.fillStyle = `rgba(23,199,143,${f})`;
      for (let i = 0; i < 6; i++) { const a = i * Math.PI / 3 + .3; ctx.beginPath(); ctx.arc(x + Math.cos(a) * t * 26, y + Math.sin(a) * t * 26 - t * 6, 2.2, 0, 7); ctx.fill(); }
    } else if (theme === "sakura") {
      ctx.strokeStyle = `rgba(244,143,177,${f * .6})`; ctx.lineWidth = 1.5;
      ctx.beginPath(); ctx.arc(x, y, 6 + t * 30, 0, 7); ctx.stroke();
      for (let i = 0; i < 8; i++) {
        const a = i * Math.PI / 4 + .3, d = t * (26 + (i % 3) * 10);
        ctx.save(); ctx.translate(x + Math.cos(a) * d, y + Math.sin(a) * d - t * 8);
        ctx.rotate(t * 3 + i); ctx.fillStyle = `rgba(${PINKS[i % PINKS.length].join(",")},${f})`;
        petalPath(4.5); ctx.restore();
      }
    } else if (theme === "glass") {
      ctx.strokeStyle = `rgba(255,107,74,${f * .7})`; ctx.lineWidth = 1.6;
      ctx.beginPath(); ctx.arc(x, y, 4 + t * 28, 0, 7); ctx.stroke();
      for (let i = 0; i < 8; i++) {
        const a = i * Math.PI / 4 + .2, d = t * (30 + (i % 2) * 10);
        ctx.fillStyle = `rgba(${EMBERS[i % 3]},${f})`;
        ctx.beginPath(); ctx.arc(x + Math.cos(a) * d, y + Math.sin(a) * d - t * 10, 1.8, 0, 7); ctx.fill();
      }
    } else if (theme === "paper") {
      const r = 3 + t * 15;
      ctx.fillStyle = `rgba(45,38,32,${f * .5})`;
      ctx.beginPath(); ctx.arc(x, y, r, 0, 7); ctx.fill();
      for (let i = 0; i < 5; i++) { const a = i * 1.256 + .5; ctx.beginPath(); ctx.arc(x + Math.cos(a) * r * .75, y + Math.sin(a) * r * .75, r * .45, 0, 7); ctx.fill(); }
      ctx.strokeStyle = `rgba(45,38,32,${f * .35})`; ctx.lineWidth = 1;
      ctx.beginPath(); ctx.arc(x, y, 6 + t * 30, 0, 7); ctx.stroke();
    } else { /* journal */
      ctx.strokeStyle = `rgba(255,179,138,${f * .6})`; ctx.lineWidth = 1.6;
      ctx.beginPath(); ctx.arc(x, y, 5 + t * 26, 0, 7); ctx.stroke();
      for (let i = 0; i < 7; i++) {
        const a = i * (Math.PI * 2 / 7) + .4, d = t * (24 + (i % 3) * 8);
        ctx.fillStyle = `rgba(${PASTELS[i % PASTELS.length]},${f * .9})`;
        ctx.beginPath(); ctx.arc(x + Math.cos(a) * d, y + Math.sin(a) * d - t * 6, 2.6, 0, 7); ctx.fill();
      }
    }
  }
  function size() {
    if (!cv) return;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    cv.width = innerWidth * dpr; cv.height = innerHeight * dpr;
    cv.style.width = innerWidth + "px"; cv.style.height = innerHeight + "px";
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  }
  function count() { return theme === "sakura" ? Math.round(Math.min(N.sakura, innerWidth / 34)) : N[theme]; }
  function reseed() {
    parts = Array.from({ length: count() }, () => initPart(innerWidth, innerHeight, true));
    bursts = [];
  }
  function frame() {
    if (!cv) return;
    const w = innerWidth, h = innerHeight, now = performance.now();
    ctx.clearRect(0, 0, w, h);
    for (const p of parts) stepPart(p, w, h);
    for (let i = bursts.length - 1; i >= 0; i--) {
      const t = (now - bursts[i].t) / 700;
      if (t >= 1) { bursts.splice(i, 1); continue; }
      drawBurst(bursts[i].x, bursts[i].y, t);
    }
    rafId = requestAnimationFrame(frame);
  }
  function start() {
    if (running || document.hidden || matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    if (!cv) {
      cv = document.createElement("canvas");
      cv.id = "fx-layer";
      cv.style.cssText = "position:fixed;left:0;top:0;z-index:95;pointer-events:none";
      document.body.appendChild(cv);
      ctx = cv.getContext("2d");
      window.addEventListener("resize", size);
      window.addEventListener("pointerdown", (e) => {
        if (e.button === 0 && running) bursts.push({ x: e.clientX, y: e.clientY, t: performance.now() });
      });
    }
    size();
    running = true;
    reseed();
    rafId = requestAnimationFrame(frame);
  }
  function stop() {
    if (!running) return;
    cancelAnimationFrame(rafId); running = false;
    if (ctx && cv) ctx.clearRect(0, 0, cv.width, cv.height);
  }
  return {
    setTheme(t) {
      theme = t;
      start();
      if (running) reseed();
    },
    stop() { stop(); },
    resume() { start(); },
  };
})();
/* 启动即按上次选择上皮肤，避免先闪一帧暗色玻璃 */
try { applyTheme(localStorage.getItem("dailylog-theme") || "glass"); } catch (_) { applyTheme("glass"); }
/* 窗口隐藏（托盘化/最小化）时停掉粒子 rAF 循环，避免后台空转撑大渲染/GPU 进程内存 */
document.addEventListener("visibilitychange", () => {
  if (document.hidden) FX.stop();
  else FX.resume();
});

/* ===================== 通用 UI ===================== */

let toastTimer = null;
function toast(msg, ms = 2600) {
  const el = document.getElementById("toast");
  el.textContent = msg;
  el.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { el.hidden = true; }, ms);
}

/* 数字滚动（GSAP 式 easeOut）：仅对「纯数字 + 非数字后缀」生效，
 * 形如 "2h30m" 的复合值直接原样显示，避免中间态错乱 */
function countUp(el, finalText) {
  const s = String(finalText);
  const m = s.match(/^(\d+)(\D*)$/);
  if (!m || matchMedia("(prefers-reduced-motion: reduce)").matches) { el.textContent = s; return; }
  const target = parseInt(m[1], 10);
  if (!target) { el.textContent = s; return; }
  const t0 = performance.now(), dur = 600;
  const tick = (t) => {
    const p = Math.min((t - t0) / dur, 1);
    el.textContent = Math.round(target * (1 - Math.pow(1 - p, 3))) + m[2];
    if (p < 1) requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);
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

const PAGES = { home: "page-home", timeline: "page-timeline", usage: "page-usage", todos: "page-todos", reports: "page-reports", logs: "page-logs", settings: "page-settings" };

document.querySelectorAll(".side-item[data-page]").forEach((item) => {
  item.addEventListener("click", () => switchPage(item.dataset.page));
});
function switchPage(name) {
  document.querySelectorAll(".side-item[data-page]").forEach((i) => i.classList.toggle("active", i.dataset.page === name));
  Object.entries(PAGES).forEach(([key, id]) => { document.getElementById(id).hidden = key !== name; });
  if (name === "home") loadHome();
  if (name === "usage") loadUsage();
  if (name === "todos") loadTodos();
  if (name === "reports") loadReports();
  if (name === "logs") loadLogs();
  if (name === "settings") loadSettings();
}

/* ===================== 今日总览页 ===================== */

async function loadHome() {
  const today = todayStr();
  const [records, todosList, usageR, reports] = await Promise.all([
    apiCall("get_records_range", today, today),
    apiCall("get_todos"),
    apiCall("get_usage_stats", "day", today),
    apiCall("list_reports"),
  ]);
  renderHome(records || MOCK_RECORDS, todosList || [], usageR, reports || []);
}

function renderHome(records, todosList, usageR, reports) {
  // 问候语 + 日期
  const h = new Date().getHours();
  document.getElementById("home-greet").textContent =
    h < 6 ? "夜深了" : h < 12 ? "上午好" : h < 14 ? "中午好" : h < 18 ? "下午好" : "晚上好";
  document.getElementById("home-date").textContent =
    `${todayStr()} ${WEEK[new Date().getDay()]} · 记录 ${records.length} 条`;

  // 专注时长（复用时间线的间隔估算法，目标按 8h 工作日）
  const totalMin = records.reduce((sum, _, i) => sum + recordDuration(records, i), 0);
  document.getElementById("home-focus-num").textContent = fmtMin(totalMin);
  const CIRC = 2 * Math.PI * 42;
  const ring = document.getElementById("home-ring");
  ring.style.strokeDasharray = CIRC;
  requestAnimationFrame(() => {
    ring.style.strokeDashoffset = CIRC * (1 - Math.min(totalMin / 480, 1));
  });

  // 关键指标
  countUp(document.getElementById("home-count"), `${records.length} 条`);
  countUp(document.getElementById("home-active"), fmtMin(totalMin));
  const openN = todosList.filter((it) => it.status === "未开始" || it.status === "进行中").length;
  countUp(document.getElementById("home-open-todos"), `${openN} 项`);
  document.getElementById("home-top-app").textContent =
    usageR && usageR.ok && usageR.apps.length ? appName(usageR.apps[0].app) : "–";

  // 时间线预览（最近 5 条，最新在上）
  const tlBox = document.getElementById("home-tl");
  if (!records.length) {
    tlBox.innerHTML = '<div class="home-empty">今天还没有记录。<br/>自动记录会替你补上接下来的每一分钟。</div>';
  } else {
    tlBox.innerHTML = [...records].reverse().slice(0, 5).map((r) => {
      const color = catColor(r.label);
      return `
      <div class="home-tl-item">
        <span class="home-tl-time">${fmtHM(r.ts)}</span>
        <span class="home-tl-bar" style="background:${color}"></span>
        <div class="home-tl-body">
          <div class="home-tl-text">${escapeHtml(r.summary || "")}</div>
          <div class="home-tl-meta">${escapeHtml(r.label || "其他")}${r.apps && r.apps.length ? " · " + escapeHtml(r.apps.join("、")) : ""}</div>
        </div>
      </div>`;
    }).join("");
    tlBox.querySelectorAll(".home-tl-item").forEach((el) => {
      el.addEventListener("click", () => switchPage("timeline"));
    });
  }

  // 应用时长 Top5（相对最大值条形）
  const appsBox = document.getElementById("home-apps");
  const topApps = usageR && usageR.ok ? usageR.apps.slice(0, 5) : [];
  if (!topApps.length) {
    appsBox.innerHTML = '<div class="home-empty">暂无应用时长采样数据。</div>';
  } else {
    const max = Math.max(...topApps.map((a) => a.minutes), 1);
    appsBox.innerHTML = topApps.map((a) => `
      <div class="app-row">
        <div class="app-top"><b title="${escapeHtml(a.app)}">${escapeHtml(appName(a.app))}</b><span>${fmtMin(a.minutes)} · ${a.pct}%</span></div>
        <div class="hbar-track-sm"><div class="hbar-fill-sm" data-w="${(a.minutes / max * 100).toFixed(1)}%"></div></div>
      </div>`).join("");
    requestAnimationFrame(() => requestAnimationFrame(() => {
      appsBox.querySelectorAll(".hbar-fill-sm").forEach((b) => { b.style.width = b.dataset.w; });
    }));
  }

  // 待办速览（未完成在前，最多 4 条，点击勾选切换完成）
  const todoBox = document.getElementById("home-todo-list");
  const PRIO_PILL = { "高": ["rgba(255,90,90,.18)", "#ff9c9c"], "中": ["rgba(255,210,127,.15)", "#ffd27f"] };
  const ordered = [...todosList.filter((it) => it.status !== "已完成" && it.status !== "归档"),
                   ...todosList.filter((it) => it.status === "已完成")].slice(0, 4);
  if (!ordered.length) {
    todoBox.innerHTML = '<div class="home-empty">没有待办，轻装上阵。</div>';
  } else {
    todoBox.innerHTML = ordered.map((it) => {
      const done = it.status === "已完成";
      const pill = PRIO_PILL[it.priority];
      return `
      <div class="home-todo-item${done ? " done" : ""}" data-id="${escapeHtml(it.id)}">
        <span class="home-todo-check">✓</span>
        <span class="home-todo-text">${mdInline(it.text)}</span>
        ${pill ? `<span class="prio-pill" style="background:${pill[0]};color:${pill[1]}">${escapeHtml(it.priority)}</span>` : ""}
      </div>`;
    }).join("");
    todoBox.querySelectorAll(".home-todo-item").forEach((el) => {
      el.addEventListener("click", async () => {
        const done = el.classList.contains("done");
        const r = await apiCall("set_todo_status", el.dataset.id, done ? "未开始" : "已完成");
        if (r && r.ok) loadHome(); else toast((r && r.error) || "更新失败");
      });
    });
  }

  // 最新报告卡
  const openBtn = document.getElementById("home-report-open");
  if (reports.length) {
    const latest = reports[0];
    document.getElementById("home-report-name").textContent = latest.name.replace(/\.md$/, "");
    document.getElementById("home-report-meta").textContent = `生成于 ${latest.mtime}`;
    openBtn.hidden = false;
    openBtn.onclick = async () => {
      const r = await apiCall("get_report", latest.name);
      if (r && r.ok) openModal(r.name, `<div class="md-body">${mdToHtml(r.content)}</div>`);
      else toast((r && r.error) || "读取失败");
    };
  } else {
    document.getElementById("home-report-name").textContent = "还没有报告";
    document.getElementById("home-report-meta").textContent = "点右上角「生成今天日报」创建第一份";
    openBtn.hidden = true;
  }
}

// 总览卡片右上角的跳转链接（data-goto → switchPage）
document.querySelectorAll(".ov-more[data-goto]").forEach((el) => {
  el.addEventListener("click", () => switchPage(el.dataset.goto));
});

/* ===================== 日志页 ===================== */

async function loadLogs() {
  const el = document.getElementById("logs-list");
  const count = document.getElementById("logs-count");
  el.innerHTML = '<div class="skeleton" style="height:160px"></div>';
  count.textContent = "";
  const r = await apiCall("get_logs");
  if (!r || !r.ok) {
    el.innerHTML = `<div class="logs-empty"><div class="empty-icon">⚠</div>读取失败：${escapeHtml(r ? r.error : "无响应")}<div class="empty-hint">请检查后端连接</div></div>`;
    return;
  }
  if (!r.logs.length) {
    el.innerHTML = '<div class="logs-empty"><div class="empty-icon">☰</div>暂无日志<div class="empty-hint">运行日志会在操作过程中自动生成</div></div>';
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
  document.getElementById("timeline").innerHTML = '<div class="skeleton" style="height:180px"></div>';
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
  countUp(document.getElementById("st-count"), n);
  const el = document.getElementById("st-range");
  const focus = document.getElementById("st-focus");
  if (!n) { el.textContent = "–"; focus.textContent = "–"; return; }
  el.textContent = `${fmtHM(timelineRecords[0].ts)} — ${fmtHM(timelineRecords[n - 1].ts)}`;
  const totalMin = timelineRecords.reduce((sum, _, i) => sum + recordDuration(timelineRecords, i), 0);
  countUp(focus, totalMin >= 60 ? `${Math.floor(totalMin / 60)}h` : `${Math.floor(totalMin)}m`);
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
    box.innerHTML = `<div class="tl-empty"><div class="empty-icon">◉</div>这个时间段还没有记录。<div class="empty-hint">放轻松，自动记录会替你补上接下来的每一分钟。</div></div>`;
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

/* ===================== 应用时长页 ===================== */

let usageScope = "day";
let usageDate = todayStr();
let usageChart = "bar";
const USAGE_COLORS = ["#ff6b4a", "#6e9eea", "#f5b94c", "#e07bd0", "#5ad1e0", "#ef6f6f", "#8b7cf5", "#ff9a76"];

/* 进程名 → 中文名（展示层映射；未知进程直接显示进程名） */
const APP_NAMES = {
  /* 桌面应用（2026-08-05 采集） */
  "cc-switch.exe": "CC Switch", "dailylog.exe": "dailylog", "kook.exe": "KOOK",
  "oopz-runner.exe": "Oopz", "plain craft launcher 2.exe": "PCL2 启动器",
  "trae cn.exe": "Trae CN", "utools.exe": "uTools", "ksolaunch.exe": "WPS Office",
  "xiadan.exe": "委托交易", "微信开发者工具.exe": "微信开发者工具",
  "douyin.exe": "抖音", "baidunetdisk.exe": "百度网盘", "feishu.exe": "飞书",
  "5eclient.exe": "5E对战平台", "another redis desktop manager.exe": "Redis 管理器",
  "apifox.exe": "Apifox", "clash-verge.exe": "Clash Verge",
  "claude code haha.exe": "Claude Code", "claude.exe": "Claude Code",
  "nvidia app.exe": "NVIDIA 应用", "obs64.exe": "OBS 录屏", "qq.exe": "QQ",
  "qqmusic.exe": "QQ音乐", "sakuralauncher.exe": "SakuraFrp 启动器",
  "steam.exe": "Steam", "vmware.exe": "VMware", "workbuddy.exe": "WorkBuddy",
  "zhuiyun.exe": "Zhuiyun", "happ.exe": "同花顺远航版", "哔哩哔哩.exe": "哔哩哔哩",
  "quark_cloud_drive.exe": "夸克网盘", "完美世界竞技平台.exe": "完美世界竞技平台",
  "小黑日报助手.exe": "小黑日报助手", "weixin.exe": "微信", "wechat.exe": "微信",
  "aclos-launcher.exe": "无畏契约", "cloudmusic.exe": "网易云音乐",
  "wemeetapp.exe": "腾讯会议", "qqlive.exe": "腾讯视频",
  /* 通用软件 */
  "chrome.exe": "谷歌浏览器", "msedge.exe": "Edge 浏览器", "firefox.exe": "火狐浏览器",
  "code.exe": "代码编辑器", "idea64.exe": "IntelliJ IDEA", "pycharm64.exe": "PyCharm",
  "explorer.exe": "文件资源管理器", "word.exe": "Word 文档", "excel.exe": "Excel 表格",
  "powerpoint.exe": "演示文稿", "wps.exe": "WPS 办公", "dingtalk.exe": "钉钉",
  "notion.exe": "Notion 笔记", "obsidian.exe": "Obsidian 笔记", "typora.exe": "Typora 笔记",
  "postman.exe": "Postman", "docker desktop.exe": "Docker",
  "wezterm.exe": "终端", "windows terminal.exe": "终端",
  "cs2.exe": "反恐精英2", "wallpaper32.exe": "壁纸引擎",
};
function appName(app) { return APP_NAMES[app] || app; }

/* 饼图扇区 SVG path：从圆心到弧（hover 可高亮，无描边） */
function pieSlice(cx, cy, r, a0, a1, color, title) {
  const rad = (a) => (a * Math.PI) / 180;
  const x0 = cx + r * Math.cos(rad(a0)), y0 = cy + r * Math.sin(rad(a0));
  const x1 = cx + r * Math.cos(rad(a1)), y1 = cy + r * Math.sin(rad(a1));
  const large = a1 - a0 > 180 ? 1 : 0;
  return `<path shape-rendering="geometricPrecision" d="M${cx},${cy} L${x0.toFixed(2)},${y0.toFixed(2)} A${r},${r} 0 ${large} 1 ${x1.toFixed(2)},${y1.toFixed(2)} Z" fill="${color}" stroke="#121014" stroke-width="2.5" stroke-linejoin="round"><title>${escapeHtml(title)}</title></path>`;
}

/* 柱状图 = 横向条形（应用名 | 条形按最大值比例 | 数值）；饼图 = SVG 实心饼 + 右侧图例 */
function renderUsageChart(apps) {
  const area = document.getElementById("chart-area");
  if (usageChart === "bar") {
    const max = Math.max(...apps.map((a) => a.minutes), 1);
    area.innerHTML = `<div class="hbar-list">` + apps.map((a) => `
      <div class="hbar-row">
        <span class="hbar-label" title="${escapeHtml(a.app)}">${escapeHtml(appName(a.app))}</span>
        <div class="hbar-track"><div class="hbar-fill" style="width:${(a.minutes / max * 100).toFixed(1)}%"></div></div>
        <span class="hbar-value">${fmtMin(a.minutes)} · ${a.pct}%</span>
      </div>`).join("") + `</div>`;
  } else {
    let acc = 0;
    const slices = apps.map((a, i) => {
      const a0 = acc * 3.6, a1 = (acc + a.pct) * 3.6;
      acc += a.pct;
      return pieSlice(250, 250, 220, a0, a1, USAGE_COLORS[i % USAGE_COLORS.length],
        `${appName(a.app)} ${fmtMin(a.minutes)} · ${a.pct}%`);
    });
    area.innerHTML = `
      <div class="pie-layout">
        <svg class="pie" viewBox="0 0 500 500" shape-rendering="geometricPrecision">${slices.join("")}</svg>
        <div class="pie-legend">` + apps.map((a, i) => `
          <div class="pie-legend-item">
            <span class="pie-swatch" style="background:${USAGE_COLORS[i % USAGE_COLORS.length]}"></span>
            <span class="pie-legend-name" title="${escapeHtml(a.app)}">${escapeHtml(appName(a.app))}</span>
            <span class="pie-legend-val">${fmtMin(a.minutes)} · ${a.pct}%</span>
          </div>`).join("") + `</div>
      </div>`;
  }
}

/* 详细列表表格（会话次数/平均会话/最长连续/首次/最后使用） */
function renderUsageTable(apps) {
  const tb = document.getElementById("usage-tbody");
  if (!apps.length) { tb.innerHTML = ""; return; }
  const fmtT = (ts) => ts ? (usageScope === "day" ? ts.slice(11, 16) : ts.slice(5, 10)) : "–";
  tb.innerHTML = apps.map((a) => `
    <tr>
      <td class="t-app" title="${escapeHtml(a.app)}">${escapeHtml(appName(a.app))}</td>
      <td>${fmtMin(a.minutes)}</td>
      <td>${a.pct}%</td>
      <td>${a.sessions}</td>
      <td>${fmtMin(a.avg)}</td>
      <td>${fmtMin(a.streak)}</td>
      <td>${fmtT(a.first)}</td>
      <td>${fmtT(a.last)}</td>
    </tr>`).join("");
}

function fmtMin(min) {
  min = Math.round(min); // 间隔估算是浮点数（如 29.9833…），显示一律取整
  if (min >= 60) {
    const h = Math.floor(min / 60), m = min % 60;
    return m ? `${h}h${m}m` : `${h}h`;
  }
  return `${min}m`;
}

function renderUsageBuckets(buckets, totalMin) {
  const box = document.getElementById("usage-buckets");
  if (!buckets.length) { box.innerHTML = ""; return; }
  const max = Math.max(...buckets.map((b) => b.minutes), 1);
  box.innerHTML = buckets.map((b) => `
    <div class="cat-item">
      <span class="cat-label">${escapeHtml(b.label)}</span>
      <div class="cat-bar"><div class="cat-fill" style="width:${(b.minutes / max * 100).toFixed(1)}%;background:var(--brand)"></div></div>
      <span class="cat-value">${fmtMin(b.minutes)}</span>
    </div>`).join("");
}

async function loadUsage() {
  document.getElementById("usage-date").value = usageDate;
  document.getElementById("chart-area").innerHTML = '<div class="skeleton" style="height:160px"></div>';
  document.getElementById("usage-tbody").innerHTML = '<div class="skeleton" style="height:120px"></div>';
  document.getElementById("usage-buckets").innerHTML = '<div class="skeleton" style="height:80px"></div>';
  const r = await apiCall("get_usage_stats", usageScope, usageDate);
  const total = document.getElementById("usage-total");
  const days = document.getElementById("usage-days");
  const apps = document.getElementById("usage-apps");
  const topApp = document.getElementById("usage-top-app");
  const topHour = document.getElementById("usage-top-hour");
  const top20 = r && r.ok ? r.apps.slice(0, 20) : [];
  if (!r || !r.ok) {
    document.getElementById("chart-area").innerHTML = `<div class="tl-empty"><div class="empty-icon">◔</div>${escapeHtml(r ? r.error : "未连接到后端")}<div class="empty-hint">请检查后端连接</div></div>`;
    renderUsageTable([]);
    total.textContent = "–"; days.textContent = "–"; apps.textContent = "–";
    topApp.textContent = "–"; topHour.textContent = "–";
    return;
  }
  countUp(total, fmtMin(r.total_min));
  countUp(days, `${r.days} 天`);
  countUp(apps, r.apps.length);
  if (!r.apps.length) {
    document.getElementById("chart-area").innerHTML = "";
    document.getElementById("usage-buckets").innerHTML = "";
    renderUsageTable([]);
    topApp.textContent = "–"; topHour.textContent = "–";
    return;
  }
  topApp.textContent = appName(r.apps[0].app);
  const peak = r.buckets.reduce((a, b) => (b.minutes > a.minutes ? b : a), r.buckets[0]);
  topHour.textContent = usageScope === "day" ? peak.label
    : (peak.label || "").slice(5).replace("-", "-");
  document.getElementById("usage-bucket-label").textContent =
    usageScope === "day" ? "按小时统计使用强度" : "按天统计使用强度";
  renderUsageChart(top20);
  renderUsageTable(top20);
  renderUsageBuckets(r.buckets, r.total_min);
}

document.querySelectorAll(".scope-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    usageScope = btn.dataset.scope;
    document.querySelectorAll(".scope-btn").forEach((b) => b.classList.toggle("active", b === btn));
    loadUsage();
  });
});
document.getElementById("usage-date").addEventListener("change", (e) => {
  if (e.target.value) { usageDate = e.target.value; loadUsage(); }
});
document.getElementById("usage-today").addEventListener("click", () => {
  usageDate = todayStr();
  document.getElementById("usage-date").value = usageDate;
  loadUsage();
});
document.querySelectorAll(".chart-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    usageChart = btn.dataset.chart;
    document.querySelectorAll(".chart-btn").forEach((b) => b.classList.toggle("active", b === btn));
    loadUsage();
  });
});

/* ===================== 日报周报页 ===================== */

async function generateReport(kind, date = "") {
  toast(date ? `正在生成 ${date} 的日报…` : (kind === "day" ? "正在生成日报…" : "正在生成周报…"));
  const r = await apiCall("generate_report", kind, date);
  if (!r) { toast("未连接到后端"); return; }
  if (!r.ok) { toast(r.error); return; }
  const title = kind === "week" ? "本周周报" : (date ? `${date} 日报` : "今日日报");
  openModal(title, `<div class="md-body">${mdToHtml(r.content)}</div>`, `保存位置：${escapeHtml(r.path)}`);
  loadReports();
  if (!document.getElementById("page-home").hidden) loadHome();  // 总览页的最新报告卡跟随刷新
}

async function loadReports() {
  const list = document.getElementById("report-list");
  list.innerHTML = '<div class="skeleton" style="height:120px"></div>';
  const items = (await apiCall("list_reports")) || [];
  document.getElementById("report-count").textContent = items.length ? `${items.length} 份` : "";
  if (!items.length) {
    list.innerHTML = `<div class="report-empty"><div class="empty-icon">▤</div>还没有生成过报告。<div class="empty-hint">点上面的按钮，用今天的轨迹写第一份日报。</div></div>`;
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
let usageEnabled = true;

function statusHtml(cfg) {
  const next = cfg.recording_enabled
    ? (cfg.test_interval_seconds ? `测试每 ${cfg.test_interval_seconds}s` : (cfg.next_capture || "—"))
    : "已停用";
  const keyDesc = cfg.has_analyze_key && cfg.has_summary_key
    ? `均已配置（${escapeHtml(cfg.analyze_key_hint || "")} / ${escapeHtml(cfg.summary_key_hint || "")}）`
    : (cfg.has_analyze_key ? "分析已配，总结未配" : (cfg.has_summary_key ? "分析未配，总结已配" : "均未配置"));
  return `
    <dt>定时记录</dt><dd class="${cfg.recording_enabled ? "ok" : "bad"}">${cfg.recording_enabled ? "运行中" : "已停用"}</dd>
    <dt>下次截屏</dt><dd>${next}</dd>
    <dt>空闲暂停</dt><dd>${cfg.idle_enabled ? `静止 ${cfg.idle_minutes} 分钟暂停` : "关闭"}</dd>
    <dt>分析模型</dt><dd>${escapeHtml(cfg.analyze_model || "未配置")}</dd>
    <dt>总结模型</dt><dd>${escapeHtml(cfg.summary_model || "未配置")}</dd>
    <dt>API Key</dt><dd>${keyDesc}</dd>`;
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
  // 皮肤以后端 settings.json 为准（localStorage 在 private_mode 下重启会丢，只作首帧兜底）
  if (cfg.theme) applyTheme(cfg.theme);
  setupSelect("theme-pop", "theme-btn", Object.keys(THEMES),
    (v) => THEMES[v], (v) => { applyTheme(v); apiCall("set_theme", v); }, cfg.theme || "glass");
  setupSelect("interval-pop", "interval-btn", cfg.interval_choices || [5, 10, 15, 30, 60],
    (m) => `每 ${m} 分钟`, (v) => { currentInterval = Number(v); autoSave(apiCall("set_interval", currentInterval), "截图间隔"); }, currentInterval);
  idleEnabled = cfg.idle_enabled !== false;
  currentIdleMin = cfg.idle_minutes || 5;
  setupSelect("idle-pop", "idle-btn", cfg.idle_choices || [1, 2, 5, 10, 15, 20, 30],
    (m) => `${m} 分钟`, (v) => { currentIdleMin = Number(v); autoSave(apiCall("set_idle", idleEnabled, currentIdleMin), "自动暂停"); }, currentIdleMin);
  document.getElementById("idle-enabled").checked = idleEnabled;
  document.getElementById("idle-btn").disabled = !idleEnabled;
  document.getElementById("idle-wrap").style.opacity = idleEnabled ? "1" : "0.45";
  document.getElementById("set-name").value = cfg.report_name || "";
  currentRetention = cfg.retention_days || 0;
  setupSelect("retention-pop", "retention-btn", cfg.retention_choices || [0, 7, 14, 30, 60, 90],
    (d) => (Number(d) === 0 ? "永久保留" : `保留 ${Number(d)} 天`), (v) => { currentRetention = Number(v); autoSave(apiCall("set_retention", currentRetention), "记录保留"); }, currentRetention);
  dedupEnabled = cfg.dedup_enabled !== false;
  document.getElementById("dedup-enabled").checked = dedupEnabled;
  enterEnabled = !!cfg.enter_capture_enabled;
  currentEnterInterval = cfg.enter_capture_interval || 15;
  setupSelect("enter-pop", "enter-btn", cfg.enter_interval_choices || [5, 15, 30, 60],
    (s) => `${s} 秒`, (v) => { currentEnterInterval = Number(v); autoSave(apiCall("set_enter_capture", enterEnabled, currentEnterInterval), "回车快速记录"); }, currentEnterInterval);
  document.getElementById("enter-enabled").checked = enterEnabled;
  document.getElementById("enter-btn").disabled = !enterEnabled;
  document.getElementById("enter-wrap").style.opacity = enterEnabled ? "1" : "0.45";
  usageEnabled = cfg.usage_enabled !== false;
  document.getElementById("usage-enabled").checked = usageEnabled;
  await fillKeyInputs();  // 输入框常驻真实 Key（password 态显示星号）
  refreshKeyStatus("analyze", cfg);
  refreshKeyStatus("summary", cfg);
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
   if (!document.getElementById("page-usage").hidden) loadUsage();  // 应用时长页可见时跟随刷新
   if (!document.getElementById("page-home").hidden) loadHome();  // 总览页可见时跟随刷新（新记录/待办变化）
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
      toast("正在分析屏幕…（约 10-60 秒）", 0); // 持久显示，完成后由后端回调替换
      await apiCall("manual_capture"); // 后台线程执行，立即返回；结果 toast 由后端推送
      refreshStatus();
    } else {
      toast(`${n} 秒后截取当前屏幕…`);
    }
  }, 1000);
}
document.getElementById("manual-capture").addEventListener("click", startManualCapture);

/* 设置改动即保存（皮肤原本就是即时保存，其余项此前只在点"保存"时落盘，
   改完直接关窗/退出会全部丢失）。失败弹 toast 提示，成功不打扰。 */
function autoSave(call, label) {
  Promise.resolve(call).then((r) => {
    if (!r || !r.ok) toast((r && r.error) || `${label}保存失败`, 5000);
  }).catch(() => toast(`${label}保存失败`, 5000));
}
document.getElementById("idle-enabled").addEventListener("change", (e) => {
  idleEnabled = e.target.checked;
  document.getElementById("idle-btn").disabled = !idleEnabled;
  document.getElementById("idle-wrap").style.opacity = idleEnabled ? "1" : "0.45";
  autoSave(apiCall("set_idle", idleEnabled, currentIdleMin), "自动暂停");
});
document.getElementById("enter-enabled").addEventListener("change", (e) => {
  enterEnabled = e.target.checked;
  document.getElementById("enter-btn").disabled = !enterEnabled;
  document.getElementById("enter-wrap").style.opacity = enterEnabled ? "1" : "0.45";
  autoSave(apiCall("set_enter_capture", enterEnabled, currentEnterInterval), "回车快速记录");
});
document.getElementById("usage-enabled").addEventListener("change", (e) => {
  usageEnabled = e.target.checked;
  autoSave(apiCall("set_usage_enabled", usageEnabled), "应用时长统计");
});
document.getElementById("dedup-enabled").addEventListener("change", (e) => {
  dedupEnabled = e.target.checked; // 此前漏绑：点这个开关根本不生效
  autoSave(apiCall("set_dedup", dedupEnabled), "跳过重复画面");
});
document.getElementById("set-name").addEventListener("change", (e) => {
  autoSave(apiCall("set_report_name", e.target.value.trim()), "汇报人");
});

/* ===================== 设置页 · API Key 配置 ===================== */

const KEY_GETTERS = {
  analyze: "在阿里云百炼（platform.aliyuncs.com）获取",
  summary: "在 DeepSeek 开放平台（platform.deepseek.com）获取",
};
const KEY_ELEMS = {
  analyze: { input: "key-analyze", eye: "key-analyze-eye", test: "key-analyze-test", status: "key-analyze-status" },
  summary: { input: "key-summary", eye: "key-summary-eye", test: "key-summary-test", status: "key-summary-status" },
};

function setKeyStatus(ch, text, cls) {
  const el = document.getElementById(KEY_ELEMS[ch].status);
  el.textContent = text;
  el.classList.remove("key-result-ok", "key-result-bad");
  if (cls) el.classList.add(cls);
}

// 状态行：已配置显示掩码 + 测试引导，未配置显示获取渠道
function refreshKeyStatus(ch, cfg) {
  const has = ch === "analyze" ? cfg.has_analyze_key : cfg.has_summary_key;
  const hint = ch === "analyze" ? cfg.analyze_key_hint : cfg.summary_key_hint;
  if (has) setKeyStatus(ch, `已配置 ${hint}，可点"测试连接"验证`, "key-result-ok");
  else setKeyStatus(ch, KEY_GETTERS[ch]);
}

// 设置页加载时回填真实 Key 到输入框（password 态显示星号，点眼睛可见）
async function fillKeyInputs() {
  const r = await apiCall("get_api_keys");
  if (r && r.ok) {
    document.getElementById("key-analyze").value = r.analyze_key || "";
    document.getElementById("key-summary").value = r.summary_key || "";
  }
}

for (const ch of Object.keys(KEY_ELEMS)) {
  const { input, eye, test } = KEY_ELEMS[ch];
  document.getElementById(eye).addEventListener("click", () => {
    const inp = document.getElementById(input);
    inp.type = inp.type === "password" ? "text" : "password";
  });
  document.getElementById(test).addEventListener("click", async () => {
    const btn = document.getElementById(test);
    btn.disabled = true;
    setKeyStatus(ch, "测试中，请稍候…");
    const r = await apiCall("test_api_connection", ch);
    btn.disabled = false;
    if (r && r.ok) setKeyStatus(ch, `✓ 连接成功 · ${(r.latency_ms / 1000).toFixed(1)} 秒`, "key-result-ok");
    else setKeyStatus(ch, `✗ ${(r && r.error) || "测试失败，请查看日志"}`, "key-result-bad");
  });
}
// 保存按钮任何情况可点：输入框常驻真实 Key（星号态），首次输入/修改/未改动统一"保存成功"；
// set_key 幂等，未改动时重写无副作用。仅任一为空时拦截并提示
document.getElementById("key-save").addEventListener("click", async () => {
  const a = document.getElementById("key-analyze").value.trim();
  const s = document.getElementById("key-summary").value.trim();
  if (!a || !s) { toast("请先输入 Key 才能使用该应用", 5000); return; }
  const r = await apiCall("save_api_keys", a, s);
  if (r && r.ok) {
    refreshKeyStatus("analyze", r);
    refreshKeyStatus("summary", r);
    toast("保存成功");
    const cfg = await apiCall("get_config");  // 同步"当前状态"面板
    if (cfg) updateStatus(cfg);
  } else {
    toast((r && r.error) || "保存失败", 5000);
  }
});

/* ===================== 待办页 ===================== */

let todoItems = [];
let todoStatusFilter = "全部状态";
let todoPriorityFilter = "全部优先级";
let todoSearch = "";

const TODO_STATUSES = ["未开始", "进行中", "已完成", "归档"];
const PRIO_COLORS = { "高": "#ef4444", "中": "#f59e0b", "低": "#6b7280" };

async function loadTodos() {
  document.getElementById("todo-list").innerHTML = '<div class="skeleton" style="height:160px"></div>';
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
    el.innerHTML = `<div class="tl-empty"><div class="empty-icon">☑</div>没有匹配的待办。<div class="empty-hint">试试调整筛选条件，或新建一条待办。</div></div>`;
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
  const ru = await apiCall("set_usage_enabled", usageEnabled);
  const results = [ri, rn, rd, rr, rdu, re, ru];
  const firstErr = results.find((r) => r && !r.ok);
  if (results.every((r) => r && r.ok)) {
    toast(`已保存：间隔每 ${ri.interval_minutes} 分钟，空闲${idleEnabled ? currentIdleMin + " 分钟暂停" : "暂停关闭"}，记录${currentRetention ? "保留 " + currentRetention + " 天" : "永久保留"}，去重${dedupEnabled ? "开" : "关"}，回车${enterEnabled ? "开" : "关"}，应用时长${usageEnabled ? "开" : "关"}${name ? "，汇报人 " + name : ""}`);
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
document.getElementById("home-gen-day").addEventListener("click", () => generateReport("day"));
// 指定日期日报：日期输入默认今天，生成时校验非空且不晚于今天
document.getElementById("gen-day-date").value = todayStr();
document.getElementById("gen-day-pick").addEventListener("click", () => {
  const d = document.getElementById("gen-day-date").value;
  if (!d) { toast("请先选择日期"); return; }
  if (d > todayStr()) { toast("不能生成未来日期的日报"); return; }
  generateReport("day", d);
});
document.getElementById("home-capture").addEventListener("click", startManualCapture);

/* ===================== 启动 ===================== */

applyRange(todayStr(), todayStr());
bindWindowDrag();
bindResizeGrip();
