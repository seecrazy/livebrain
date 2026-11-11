/* 播控大脑运营控制台前端（原生 JS，800ms 轮询，无构建链） */
"use strict";

const $ = (id) => document.getElementById(id);
let lastState = null;

/* ---------- API ---------- */
async function fetchState() {
  const res = await fetch("/api/state", { cache: "no-store" });
  if (!res.ok) throw new Error("state " + res.status);
  return res.json();
}

async function postControl(action, params = {}) {
  try {
    const res = await fetch("/api/control", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action, params }),
    });
    const data = await res.json();
    if (!data.ok) console.warn("control rejected:", data.detail);
  } catch (err) {
    console.error("control error:", err);
  }
  refresh();                      // 立即拉一次状态
}

function takeover() {
  if (confirm("确认接管？AI 将静默并切换真人画面。")) {
    postControl("takeover", { reason: "console_hotkey" });
  }
}

function applyDemoSchedule() {
  postControl("demo_schedule", {
    segments: [
      { duration_s: 25, mode: "ai", label: "AI 讲解段" },
      { duration_s: 20, mode: "human", label: "真人主推段" },
      { duration_s: 25, mode: "ai", label: "AI 返场段" },
    ],
  });
}

/* ---------- 渲染 ---------- */
const INTENT_TAG = {
  price_stock: ["fast", "价格/库存"],
  product_consult: ["mid", "咨询"],
  interact: ["interact", "互动"],
  sensitive: ["sensitive", "敏感"],
  action_request: ["action", "诱导"],
  noise: ["noise", "噪音"],
  injection: ["inject", "注入"],
};
const TRACK_TAG = {
  fast: ["fast", "快轨"],
  mid: ["mid", "中轨"],
  template: ["template", "模板"],
  fallback: ["fallback", "兜底"],
};

function chip(text, cls) {
  return `<span class="chip ${cls || ""}">${text}</span>`;
}

function renderTopbar(s) {
  const stageNames = {
    warmup: "暖场期", explain: "讲解期", closing: "逼单期", valley: "低谷期",
  };
  $("status-chips").innerHTML = [
    chip(`阶段 <b>${stageNames[s.stage] || s.stage}</b>`, "stage"),
    chip(`人设 <b>${s.persona_name}</b>`, "persona"),
    chip(s.mode === "human" ? "<b>真人在场</b>" : "<b>AI 主播</b>",
         s.mode === "human" ? "mode-human" : "mode-ai"),
    chip(`在线 <b>${s.online}</b>`, "online"),
    chip(`品 <b>${s.current_sku}</b>`, ""),
    chip(`LLM <b>${s.providers.llm}</b>`, ""),
  ].join("");
  const audit = $("audit-badge");
  audit.textContent = s.audit.verified
    ? `审计链 ✓ ${s.audit.count} 条` : `审计链 ✗ 异常`;
  audit.className = "audit" + (s.audit.verified ? "" : " bad");

  const esc = $("escalation");
  esc.hidden = !s.escalation.active;
  if (s.escalation.active) $("escalation-reason").textContent = s.escalation.reason;
}

function renderStage(s) {
  const human = s.visual_source === "human";
  $("avatar-orb").style.opacity = human ? 0.15 : 1;
  $("human-cam").hidden = !human;
  const badgeOff = s.visual_source === "human" && s.compliance.policy === "ai_content_only";
  $("ai-badge").classList.toggle("off", badgeOff);
  const speaking = s.speech.length > 0 && !s.speech[0].interrupted;
  $("avatar-orb").classList.toggle("speaking", speaking && !human);
  $("stage-meta").textContent =
    `画面源 ${s.visual_source} · 标识策略 ${s.compliance.policy || "-"}` +
    (s.compliance.armed ? "" : " · ⚠标识未武装");
}

function renderOps(s) {
  $("btn-takeover").disabled = s.mode === "human";
  $("btn-rehandoff").disabled = s.mode !== "human";
}

function renderSpeech(s) {
  const box = $("speech");
  if (!s.speech.length) { box.innerHTML = '<div class="empty">等待开播…</div>'; }
  else {
    box.innerHTML = s.speech.map((u) => {
      const [cls, name] = TRACK_TAG[u.track] || ["noise", u.track];
      return `<div class="item">
        <div class="meta">
          <span class="tag ${cls}">${name}</span>
          <span class="tag noise">${u.source}</span>
          <span class="tag noise">${u.emotion}</span>
          ${u.interrupted ? '<span class="tag interrupted">⚡被打断</span>' : ""}
        </div>
        <div>${escapeHtml(u.text)}</div>
        ${u.origin ? `<div class="origin">↳ ${escapeHtml(u.origin)}</div>` : ""}
      </div>`;
    }).join("");
  }
  $("speech-stats").textContent =
    `共 ${s.stats.utterances} 条 · 打断 ${s.stats.interrupted} 次`;
}

function renderDanmu(s) {
  const box = $("danmu");
  if (!s.danmu_feed.length) { box.innerHTML = '<div class="empty">等待弹幕…</div>'; return; }
  box.innerHTML = s.danmu_feed.map((d) => {
    const [cls, name] = INTENT_TAG[d.intent] || ["noise", d.intent];
    return `<div class="item ${d.quarantined ? "quarantined" : ""}">
      <div class="meta">
        <span class="tag ${cls}">${d.quarantined ? "已隔离" : name}</span>
        <span class="origin">${d.user}</span>
      </div>
      <div class="text">${escapeHtml(d.text)}</div>
    </div>`;
  }).join("");
}

function renderLists(s) {
  $("promises").innerHTML = s.promises.length
    ? s.promises.map((p) => `<div class="item">
        <div class="meta">
          <span class="tag ${p.status === "fulfilled" ? "mid" : "fallback"}">${p.status}</span>
          <span class="tag noise">${p.action}</span>
          ${p.failures ? `<span class="tag interrupted">重试 ${p.failures}</span>` : ""}
        </div>
      </div>`).join("")
    : '<div class="empty">暂无</div>';

  const alerts = [...s.judgments.map((j) => `[判罚] ${j.reason}`),
                  ...s.alerts].slice(-8);
  $("alerts").innerHTML = alerts.length
    ? alerts.map((a) => `<div class="item"><div>${escapeHtml(a)}</div></div>`).join("")
    : '<div class="empty">一切正常</div>';

  $("runtime-stats").innerHTML = [
    ["话术总数", s.stats.utterances],
    ["注入隔离", s.audit.quarantined],
    ["生成拦截", s.audit.generation_rejected],
    ["承诺拦截", s.audit.promise_blocks],
    ["LLM 切换", s.providers.llm_switches],
    ["审计条目", s.audit.count],
    ["排班段", s.mixed.segments.length ? `${s.mixed.pos + 1}/${s.mixed.segments.length}` : "未启用"],
    ["排班模式", s.mixed.segments.length ? s.mixed.current_mode : "-"],
  ].map(([k, v]) => `<div>${k}<b>${v}</b></div>`).join("");
}

function escapeHtml(text) {
  return String(text ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[c]);
}

function render(s) {
  lastState = s;
  renderTopbar(s);
  renderStage(s);
  renderOps(s);
  renderSpeech(s);
  renderDanmu(s);
  renderLists(s);
}

async function refresh() {
  try {
    render(await fetchState());
  } catch (err) {
    console.error("refresh error:", err);
  }
}

/* 快捷键：T=接管 R=交回 */
document.addEventListener("keydown", (e) => {
  if (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA") return;
  if (e.key === "t" || e.key === "T") takeover();
  if ((e.key === "r" || e.key === "R") && lastState && lastState.mode === "human") {
    postControl("rehandoff");
  }
});

refresh();
setInterval(refresh, 800);
