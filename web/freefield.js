// Freefield's apps in a ComfyUI sidebar tab: browse them by category, see what this ComfyUI still needs for one
// (model files, node types), download its models, and open its workflow in a new tab, with the lab's example filled in.
// "Download" gets the files the workflow loads; LoRAs for an app's other choices have a button of their own.
import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

const REPO = "https://github.com/neuregex/freefield";
const state = { data: null, cat: "all", query: "", readyOnly: false, openId: null, el: null, poll: null };

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const gb = (x) => (x >= 10 ? x.toFixed(0) : x.toFixed(1)) + " GB";

function toast(severity, detail, life = 4000) {
  const t = app.extensionManager?.toast;
  if (t?.add) t.add({ severity, summary: "Freefield", detail, life });
  else console[severity === "error" ? "error" : "log"]("[freefield]", detail);
}

async function getJSON(path, opts) {
  const r = await api.fetchApi(path, opts);
  const d = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(d.error || `${path}: HTTP ${r.status}`);
  return d;
}

async function load() {
  state.data = await getJSON("/freefield/catalog");
  render();
  if (Object.values(state.data.downloads || {}).some(busy)) startPolling();
}

const busy = (j) => j && (j.state === "queued" || j.state === "downloading");
const jobOf = (id) => state.data?.downloads?.[id];

function badges(a) {
  const s = a.status, out = [];
  const j = jobOf(a.id);
  if (busy(j)) out.push(`<span class="ff-badge ff-dl">${pct(j)}%</span>`);
  else if (s.ready) out.push(`<span class="ff-badge ff-ok">Ready</span>`);
  else if (s.node_types_missing.length) out.push(`<span class="ff-badge ff-warn">Needs nodes</span>`);
  else out.push(`<span class="ff-badge">${gb(s.missing_gb)} to get</span>`);
  if (a.tested) out.push(`<span class="ff-badge ff-tested" title="${esc(testedTitle(a.tested))}">Ran on ${a.tested.machine.vram_gb} GB</span>`);
  else if (a.vram?.fit) out.push(`<span class="ff-badge ff-dim" title="Freefield's estimate from weight sizes">${esc(a.vram.fit)}</span>`);
  return out.join("");
}

// apps that ran on a 24 GB card through this node (tested/*.json); the others keep Freefield's estimate from weight sizes
const gpuName = (g) => String(g || "").replace(/^NVIDIA (GeForce )?/, "");
const runTime = (r) => (r.seconds != null ? `${Math.round(r.seconds)} s` : r.range ? `${r.range[0]}–${r.range[1]} s` : "");
const testedTitle = (t) => `${gpuName(t.machine.gpu)}, ${t.machine.ram_gb} GB of RAM, ${t.machine.os}, ${t.date}`;

function vramLine(a) {
  const t = a.tested, est = a.vram?.fit ? esc(a.vram.fit) : "";
  if (!t) return est ? `${est} (Freefield's estimate from weight sizes; not run on 24 GB here yet)` : "";
  const m = t.machine, time = runTime(t.runs[0] || {});   // the first run is the example as the tab opens it
  return `Ran on an ${esc(gpuName(m.gpu))} (${m.vram_gb} GB) with ${m.ram_gb} GB of RAM${time ? ` in ${time}` : ""}, `
    + `${esc(m.os)}, ${esc(t.date)}${est ? ` · Freefield's estimate from weight sizes: ${est}` : ""}`;
}

const pct = (j) => (j.total_bytes ? Math.min(100, Math.floor((100 * j.done_bytes) / j.total_bytes)) : 0);
const thumb = (a) => (a.thumb ? api.apiURL(`/freefield/thumb/${encodeURIComponent(a.id)}`) : "");

function matches(a) {
  if (state.cat !== "all" && a.category !== state.cat) return false;
  if (state.readyOnly && !a.status.ready) return false;
  const q = state.query.trim().toLowerCase();
  return !q || [a.name, a.summary, a.higgsfield_feature, a.id].some((x) => String(x ?? "").toLowerCase().includes(q));
}

function card(a) {
  return `<button class="ff-card" data-open="${esc(a.id)}" title="${esc(a.summary)}">
    <div class="ff-thumb">${a.thumb ? `<img loading="lazy" src="${thumb(a)}" alt="">` : ""}</div>
    <div class="ff-card-name">${esc(a.name)}</div>
    <div class="ff-badges">${badges(a)}</div>
  </button>`;
}

function listView() {
  const d = state.data;
  const shown = d.apps.filter(matches);
  const cats = d.categories.filter((c) => d.apps.some((a) => a.category === c.id));
  const chips = [{ id: "all", title: "All" }, ...cats]
    .map((c) => `<button class="ff-chip${state.cat === c.id ? " ff-on" : ""}" data-cat="${c.id}">${esc(c.title)}</button>`).join("");
  const groups = (state.cat === "all" ? cats : cats.filter((c) => c.id === state.cat))
    .map((c) => ({ c, apps: shown.filter((a) => a.category === c.id) }))
    .filter((g) => g.apps.length)
    .map((g) => `<section class="ff-group"><h4 title="${esc(g.c.desc)}">${esc(g.c.title)} <span>${g.apps.length}</span></h4>
       <div class="ff-grid">${g.apps.map(card).join("")}</div></section>`).join("");
  const ready = d.apps.filter((a) => a.status.ready).length;
  return `<div class="ff-head">
      <div class="ff-title"><b>Freefield</b><span>${d.apps.length} apps · ${ready} ready here</span></div>
      <input class="ff-search" type="search" placeholder="Search apps" value="${esc(state.query)}">
      <label class="ff-toggle"><input type="checkbox" ${state.readyOnly ? "checked" : ""} data-ready> Only apps ready to run</label>
      <div class="ff-chips">${chips}</div>
    </div>
    <div class="ff-body">${groups || `<p class="ff-empty">No app matches.</p>`}</div>
    <div class="ff-foot">Apps from <a href="${REPO}" target="_blank" rel="noopener">neuregex/freefield</a> @ ${esc(d.source.ref.slice(0, 7))} · open weights only</div>`;
}

function modelRows(models, missing) {
  return models.map((m) => `<li class="${missing.has(m.name) ? "ff-missing" : "ff-have"}">
      <span class="ff-mark">${missing.has(m.name) ? "○" : "●"}</span>
      <span class="ff-file" title="${esc(m.repo)}/${esc(m.file)}">${esc(m.name)}</span>
      <span class="ff-size">${gb(m.gb)}</span>
      <small>${esc(m.dir)} · ${esc(m.license)}${m.gated ? " · gated" : ""}</small>
    </li>`).join("");
}

// extra=false: the files the workflow loads; extra=true: the LoRAs of the app's other choices
function downloadBlock(a, extra) {
  const s = a.status, j = jobOf(a.id);
  if (busy(j)) {
    if (!!j.extra !== extra) return "";   // the other set is downloading: one set per app at a time
    return `<div class="ff-progress"><div style="width:${pct(j)}%"></div></div>
      <p class="ff-note">${esc(j.state === "queued" ? "Queued" : `Downloading ${j.current || ""}`)} · ${pct(j)}% of ${gb(j.total_bytes / 1e9)}
      · file ${Math.min(j.files_done + 1, j.files_total)} of ${j.files_total}</p>`;
  }
  const err = j?.state === "error" && !!j.extra === extra ? `<p class="ff-error">${esc(j.error)}</p>` : "";
  const missing = extra ? s.extra_missing : s.needed_missing;
  if (!missing.length) return err;
  const gated = a.models.some((m) => m.gated && missing.includes(m.name));
  const label = extra ? `Download these too · ${gb(s.extra_missing_gb)}` : `Download ${gb(s.missing_gb)}`;
  return `${err}<button class="ff-btn" data-act="${extra ? "download-extra" : "download"}">${label}</button>
    ${gated ? `<p class="ff-note">Gated files: accept the license on Hugging Face, then <code>hf auth login</code> or set <code>HF_TOKEN</code> before starting ComfyUI.</p>` : ""}`;
}

function modelsBlocks(a) {
  const s = a.status, missing = new Set(s.models_missing);
  const need = a.models.filter((m) => !m.extra), extra = a.models.filter((m) => m.extra);
  const head = need.length ? (s.needed_missing.length ? `<span>${s.needed_missing.length} of ${need.length} missing</span>` : "<span>all here</span>") : "<span>none</span>";
  let out = `<div class="ff-block"><h4>Models ${head}</h4>
      <ul class="ff-models">${modelRows(need, missing)}</ul>${downloadBlock(a, false)}</div>`;
  if (extra.length) {
    out += `<div class="ff-block"><h4>Other choices <span>${s.extra_missing.length ? `${s.extra_missing.length} of ${extra.length} missing` : "all here"}</span></h4>
      <p class="ff-note">LoRAs the workflow does not load as it opens: another effect or style, or one to add yourself. Download them to pick them in its LoRA loader.</p>
      <ul class="ff-models">${modelRows(extra, missing)}</ul>${downloadBlock(a, true)}</div>`;
  }
  return out;
}

function detailView(a) {
  const s = a.status, ex = a.example;
  const sibling = (a.modes || []).filter((m) => m !== a.id).map((m) => state.data.apps.find((x) => x.id === m)).filter(Boolean);
  const nodesWarn = s.node_types_missing.length
    ? `<div class="ff-block ff-warnbox"><h4>Missing node types</h4>
        <p>${a.custom_nodes?.length
          ? `Install ${a.custom_nodes.map((c) => `<a href="${esc(c.repo)}" target="_blank" rel="noopener">${esc(c.name)}</a>`).join(", ")} (ComfyUI Manager can do it), then restart ComfyUI.`
          : "Update ComfyUI: this app uses core nodes newer than yours."}</p>
        <p class="ff-note">${s.node_types_missing.map(esc).join(", ")}</p></div>` : "";
  const exLine = ex ? `Lab example: ${ex.seconds ? `${Math.round(ex.seconds)} s` : ""} on ${esc(ex.gpu || "a GPU")}${ex.peak_vram_gb ? `, peak ${ex.peak_vram_gb} GB` : ""}` : "";
  return `<div class="ff-detail">
    <button class="ff-back" data-back>‹ All apps</button>
    ${a.thumb ? `<img class="ff-hero" src="${thumb(a)}" alt="">` : ""}
    <h3>${esc(a.name)}</h3>
    <p>${esc(a.summary)}</p>
    <p class="ff-note">${a.higgsfield_feature ? `Rebuilds Higgsfield's ${esc(a.higgsfield_feature)}. ` : ""}${exLine}</p>
    ${vramLine(a) ? `<p class="ff-note ff-vram">${vramLine(a)}</p>` : ""}
    ${sibling.length ? `<p class="ff-note">${esc(a.mode_label || "Mode")}: ${sibling.map((x) => `<a href="#" data-open="${esc(x.id)}">${esc(x.name)}</a>`).join(", ")}</p>` : ""}
    <div class="ff-actions">
      ${ex ? `<button class="ff-btn ff-primary" data-act="example">Open with example</button>` : ""}
      <button class="ff-btn" data-act="empty">Open empty</button>
    </div>
    ${ex?.needs?.length ? `<p class="ff-note">The example leaves out: ${ex.needs.map((n) => esc(n.label)).join(", ")}. Add your own in its loader node.</p>` : ""}
    ${nodesWarn}
    ${modelsBlocks(a)}
    <p class="ff-note"><a href="${REPO}/tree/main/apps/${esc(a.id)}" target="_blank" rel="noopener">How it works</a> · every model's license is in its app.json</p>
  </div>`;
}

function render() {
  const el = state.el;
  if (!el || !state.data) return;
  const a = state.openId && state.data.apps.find((x) => x.id === state.openId);
  const scroll = el.querySelector(".ff-body, .ff-detail")?.scrollTop ?? 0;
  el.innerHTML = `<div class="ff-root">${a ? detailView(a) : listView()}</div>`;
  const pane = el.querySelector(".ff-body, .ff-detail");
  if (pane) pane.scrollTop = scroll;
}

async function openApp(id, example) {
  const a = state.data.apps.find((x) => x.id === id);
  try {
    const d = await getJSON("/freefield/open", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ id, example }) });
    if (d.files?.length) await app.refreshComboInNodes?.();   // the example's files are new in the input folder
    await app.loadApiJson(d.prompt, d.filename);   // opens as its own workflow tab named after the app
    try { await app.extensionManager?.command?.execute?.("Comfy.Canvas.FitView"); } catch { /* older frontends */ }
    const missing = a.status.ready ? "" : " Some models or nodes are still missing: see the Freefield tab.";
    toast(a.status.ready ? "success" : "warn", `${a.name} is loaded${d.example ? " with its example" : ""}. Press Run.${missing}`, 6000);
  } catch (e) {
    toast("error", `Could not open ${a?.name || id}: ${e.message}`, 8000);
  }
}

async function download(id, extra) {
  try {
    const j = await getJSON("/freefield/download", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ id, extra }) });
    state.data.downloads = { ...state.data.downloads, [id]: j };
    render();
    startPolling();
  } catch (e) {
    toast("error", e.message, 8000);
  }
}

function startPolling() {
  if (state.poll) return;
  state.poll = setInterval(async () => {
    try {
      const jobs = await getJSON("/freefield/downloads");
      const was = Object.entries(state.data.downloads || {}).filter(([, j]) => busy(j)).map(([k]) => k);
      state.data.downloads = jobs;
      const ended = was.filter((k) => !busy(jobs[k]));
      for (const k of ended) {
        const j = jobs[k], a = state.data.apps.find((x) => x.id === k);
        if (j?.state === "done") toast("success", `${a?.name || k}: models downloaded.`);
        else if (j?.state === "error") toast("error", `${a?.name || k}: ${j.error}`, 10000);
      }
      if (ended.length) await load();   // statuses changed
      else render();
      if (!Object.values(jobs).some(busy)) { clearInterval(state.poll); state.poll = null; }
    } catch { /* the server restarted: keep trying */ }
  }, 1500);
}

function mount(el) {
  state.el = el;
  if (!document.getElementById("ff-style")) {
    const link = document.createElement("link");
    link.id = "ff-style";
    link.rel = "stylesheet";
    link.href = new URL("./freefield.css", import.meta.url).href;
    document.head.appendChild(link);
  }
  el.addEventListener("click", (ev) => {
    const t = ev.target.closest("[data-open],[data-cat],[data-back],[data-act]");
    if (!t) return;
    ev.preventDefault();
    if (t.dataset.open) { state.openId = t.dataset.open; render(); el.querySelector(".ff-detail")?.scrollTo(0, 0); }
    else if (t.dataset.cat) { state.cat = t.dataset.cat; render(); }
    else if ("back" in t.dataset) { state.openId = null; render(); }
    else if (t.dataset.act === "example" || t.dataset.act === "empty") openApp(state.openId, t.dataset.act === "example");
    else if (t.dataset.act === "download" || t.dataset.act === "download-extra") download(state.openId, t.dataset.act === "download-extra");
  });
  el.addEventListener("input", (ev) => {
    if (ev.target.classList.contains("ff-search")) {
      state.query = ev.target.value;
      const pos = ev.target.selectionStart;
      render();
      const s = el.querySelector(".ff-search");
      s?.focus();
      s?.setSelectionRange(pos, pos);
    }
  });
  el.addEventListener("change", (ev) => {
    if ("ready" in ev.target.dataset) { state.readyOnly = ev.target.checked; render(); }
  });
  if (state.data) render();
  load().catch((e) => { el.innerHTML = `<div class="ff-root"><p class="ff-error">Freefield: ${esc(e.message)}</p></div>`; });
}

app.registerExtension({
  name: "Freefield.Apps",
  setup() {
    const tab = { id: "freefield", icon: "pi pi-th-large", title: "Freefield", tooltip: "Freefield apps", type: "custom", render: mount };
    if (app.extensionManager?.registerSidebarTab) app.extensionManager.registerSidebarTab(tab);
    else console.warn("[freefield] this ComfyUI frontend has no sidebar tabs; update ComfyUI to use Freefield's panel");
  },
});
