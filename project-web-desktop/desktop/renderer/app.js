const API = 'http://127.0.0.1:8765';
const SUPPORT_URL = 'https://github.com/sponsors/piotrgrechuta-web';
const REPO_URL = 'https://github.com/piotrgrechuta-web/epu2pl';

const FORM_IDS = [
  'mode', 'provider', 'model', 'input_epub', 'output_epub', 'prompt', 'glossary', 'cache', 'ollama_host',
  'google_api_key', 'source_lang', 'target_lang', 'timeout', 'attempts', 'backoff', 'batch_max_segs',
  'batch_max_chars', 'sleep', 'temperature', 'num_ctx', 'num_predict', 'tags', 'use_cache', 'use_glossary',
];
const PROFILE_IDS = [
  'provider', 'model', 'debug_dir', 'ollama_host', 'batch_max_segs', 'batch_max_chars', 'sleep', 'timeout',
  'attempts', 'backoff', 'temperature', 'num_ctx', 'num_predict', 'tags', 'use_cache', 'use_glossary',
  'checkpoint', 'source_lang', 'target_lang',
];

const verEl = document.getElementById('ver');
const msgEl = document.getElementById('msg');
const statusEl = document.getElementById('status');
const runMetricsEl = document.getElementById('run_metrics');
const countsEl = document.getElementById('counts');
const projectSummaryEl = document.getElementById('project_summary');
const logEl = document.getElementById('log');
const historyEl = document.getElementById('history');
const setupWinEl = document.getElementById('setup-win');
const setupLinuxEl = document.getElementById('setup-linux');
const setupMacEl = document.getElementById('setup-macos');
const setupHintEl = document.getElementById('os-hint');
const modelEl = document.getElementById('model');

const projectSelectEl = document.getElementById('project_select');
const modeEl = document.getElementById('mode');
const profileSelectEl = document.getElementById('profile_select');
const runAllBtn = document.getElementById('run-all-btn');
const stopRunAllBtn = document.getElementById('stop-run-all-btn');

const APP_INFO = (window.appInfo && typeof window.appInfo === 'object')
  ? window.appInfo
  : { name: 'Translator Studio Desktop', version: '0.0.0', platform: (navigator.platform || '') };
if (verEl) verEl.textContent = `${APP_INFO.name} v${APP_INFO.version}`;

window.addEventListener('error', (ev) => {
  const msg = ev?.error?.message || ev?.message || 'Nieznany blad JS';
  message(`Blad JS: ${msg}`, true);
});
window.addEventListener('unhandledrejection', (ev) => {
  const msg = ev?.reason?.message || String(ev?.reason || 'Nieznany blad Promise');
  message(`Blad Promise: ${msg}`, true);
});

let currentProjectId = null;
let tmDbPath = 'translator_studio.db';
let profiles = [];
let stepValues = {
  translate: { output: '', prompt: '', cache: '', profile_id: null },
  edit: { output: '', prompt: '', cache: '', profile_id: null },
};
let runAllActive = false;
let runAllBusy = false;
let prevRunning = false;
let suppressModeEvent = false;

const setupCommands = {
  windows: [
    '# Ollama (lokalnie)',
    'winget install Ollama.Ollama',
    'ollama pull llama3.1:8b',
    '',
    '# API key (provider online, np. Google Gemini)',
    'setx GOOGLE_API_KEY "<TWOJ_KLUCZ>"',
  ],
  linux: [
    '# Ollama (lokalnie)',
    'curl -fsSL https://ollama.com/install.sh | sh',
    'ollama pull llama3.1:8b',
    '',
    '# API key (provider online, np. Google Gemini)',
    'export GOOGLE_API_KEY="<TWOJ_KLUCZ>"',
  ],
  macos: [
    '# Ollama (lokalnie)',
    'brew install ollama',
    'ollama pull llama3.1:8b',
    '',
    '# API key (provider online, np. Google Gemini)',
    'export GOOGLE_API_KEY="<TWOJ_KLUCZ>"',
  ],
};

function normalizePlatform() {
  const p = String(APP_INFO.platform || '').toLowerCase();
  if (p.startsWith('win')) return 'windows';
  if (p === 'darwin') return 'macos';
  return 'linux';
}

function setupGuideText() {
  return [
    'Windows (PowerShell):',
    ...setupCommands.windows,
    '',
    'Linux:',
    ...setupCommands.linux,
    '',
    'macOS:',
    ...setupCommands.macos,
  ].join('\n');
}

function renderSetupGuide() {
  if (!setupWinEl || !setupLinuxEl || !setupMacEl || !setupHintEl) return;
  setupWinEl.textContent = setupCommands.windows.join('\n');
  setupLinuxEl.textContent = setupCommands.linux.join('\n');
  setupMacEl.textContent = setupCommands.macos.join('\n');
  const current = normalizePlatform();
  const label = current === 'windows' ? 'Windows' : (current === 'macos' ? 'macOS' : 'Linux');
  setupHintEl.textContent = `Wykryty system: ${label}`;
}

async function copySetupGuide() {
  const text = setupGuideText();
  try {
    await navigator.clipboard.writeText(text);
    message('Skopiowano instrukcje pierwszego uruchomienia.');
  } catch {
    try {
      const ta = document.createElement('textarea');
      ta.value = text;
      ta.style.position = 'fixed';
      ta.style.left = '-9999px';
      document.body.appendChild(ta);
      ta.select();
      const ok = document.execCommand('copy');
      document.body.removeChild(ta);
      if (!ok) throw new Error('Clipboard command returned false');
      message('Skopiowano instrukcje pierwszego uruchomienia.');
    } catch (e) {
      message(`Nie udalo sie skopiowac instrukcji: ${e.message || e}`, true);
    }
  }
}

function modeNorm(v) {
  return v === 'edit' ? 'edit' : 'translate';
}

function val(id) {
  const el = document.getElementById(id);
  if (!el) return '';
  if (el.type === 'checkbox') return !!el.checked;
  return el.value;
}

function setVal(id, value) {
  const el = document.getElementById(id);
  if (!el) return;
  if (el.type === 'checkbox') {
    el.checked = !!value;
  } else {
    el.value = value ?? '';
  }
}

function currentMode() {
  return modeNorm(String(val('mode') || 'translate'));
}

function selectedProfileId() {
  const raw = String(profileSelectEl.value || '').trim();
  if (!raw) return null;
  const n = Number(raw);
  return Number.isFinite(n) ? n : null;
}

function captureCurrentStep() {
  const m = currentMode();
  stepValues[m] = {
    output: String(val('output_epub') || ''),
    prompt: String(val('prompt') || ''),
    cache: String(val('cache') || ''),
    profile_id: selectedProfileId(),
  };
}

function applyStepToForm(mode) {
  const m = modeNorm(mode);
  const step = stepValues[m] || { output: '', prompt: '', cache: '', profile_id: null };
  setVal('output_epub', step.output || '');
  setVal('prompt', step.prompt || '');
  setVal('cache', step.cache || '');
  profileSelectEl.value = step.profile_id == null ? '' : String(step.profile_id);
}

function collectState() {
  const out = {};
  for (const id of FORM_IDS) out[id] = val(id);
  out.mode = currentMode();
  out.debug_dir = 'debug';
  out.checkpoint = '0';
  out.tm_db = tmDbPath || 'translator_studio.db';
  out.tm_project_id = currentProjectId;
  return out;
}

function applyState(state) {
  for (const id of FORM_IDS) {
    if (Object.prototype.hasOwnProperty.call(state, id)) setVal(id, state[id]);
  }
  if (state.tm_db) tmDbPath = String(state.tm_db);
  suppressModeEvent = true;
  setVal('mode', modeNorm(String(state.mode || 'translate')));
  suppressModeEvent = false;
}

async function api(path, opts = {}) {
  const r = await fetch(`${API}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...opts,
  });
  const body = await r.text();
  let data = {};
  try { data = JSON.parse(body); } catch {}
  if (!r.ok) throw new Error(data.detail || body || `HTTP ${r.status}`);
  return data;
}

function message(text, isErr = false) {
  if (!msgEl) {
    console[isErr ? 'error' : 'log'](text);
    return;
  }
  msgEl.textContent = text;
  msgEl.className = isErr ? 'msg err' : 'msg ok';
}

function formatTs(ts) {
  const n = Number(ts || 0);
  if (!n) return '-';
  const d = new Date(n * 1000);
  return d.toLocaleString();
}

function updateCounts(counts) {
  const c = counts || {};
  if (!countsEl) return;
  countsEl.textContent = `idle=${c.idle || 0} | pending=${c.pending || 0} | running=${c.running || 0} | error=${c.error || 0}`;
}

function normalizeProjectStatus(status) {
  const s = String(status || 'idle').toLowerCase();
  const map = {
    none: 'idle',
    ready: 'idle',
    queued: 'pending',
    queue: 'pending',
    needs_review: 'error',
    fail: 'error',
    failed: 'error',
    done: 'ok',
    success: 'ok',
  };
  if (['idle', 'pending', 'running', 'error', 'ok'].includes(s)) return s;
  return map[s] || 'idle';
}

function normalizeStageStatus(status) {
  const s = String(status || 'none').toLowerCase();
  const map = {
    queued: 'pending',
    queue: 'pending',
    in_progress: 'running',
    done: 'ok',
    success: 'ok',
    fail: 'error',
    failed: 'error',
  };
  if (['none', 'idle', 'pending', 'running', 'ok', 'error'].includes(s)) return s;
  return map[s] || 'none';
}

function shortText(value, maxLen = 42) {
  const text = String(value || '').trim();
  if (maxLen <= 3 || text.length <= maxLen) return text;
  return `${text.slice(0, maxLen - 3)}...`;
}

function stageStatusLabel(status) {
  return normalizeStageStatus(status);
}

function nextActionLabel(action) {
  const a = String(action || '').toLowerCase();
  const map = {
    done: 'koniec',
    translate: 'T',
    translate_retry: 'T!',
    edit: 'R',
    edit_retry: 'R!',
    'running:translate': 'run T',
    'running:edit': 'run R',
    'pending:translate': 'q T',
    'pending:edit': 'q R',
  };
  return map[a] || a || '-';
}

function projectSummaryText(project) {
  const p = project || {};
  const tr = p.translate || {};
  const ed = p.edit || {};
  const book = String(p.book || '-');
  const tDone = Number(tr.done || 0);
  const tTotal = Number(tr.total || 0);
  const eDone = Number(ed.done || 0);
  const eTotal = Number(ed.total || 0);
  const shortBook = shortText(book, 46);
  return `ks=${shortBook} | T:${tDone}/${tTotal} ${stageStatusLabel(tr.status)} | R:${eDone}/${eTotal} ${stageStatusLabel(ed.status)} | -> ${nextActionLabel(p.next_action)}`;
}

function renderProjectSummary(project) {
  if (!projectSummaryEl) return;
  if (!project) {
    projectSummaryEl.textContent = '';
    return;
  }
  projectSummaryEl.textContent = projectSummaryText(project);
}

function setRunAllButtons() {
  if (!runAllBtn || !stopRunAllBtn) return;
  runAllBtn.disabled = runAllActive;
  stopRunAllBtn.disabled = !runAllActive;
}

function formatDuration(seconds) {
  const sec = Number(seconds || 0);
  if (!sec || sec < 0) return '-';
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  const s = Math.floor(sec % 60);
  if (h > 0) return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
}

function runMetricsText(run) {
  const r = run || {};
  const m = r.metrics || {};
  const step = String(r.step || '-');
  const status = normalizeStageStatus(r.status || 'none');
  const done = Number(m.done ?? r.global_done ?? 0);
  const total = Number(m.total ?? r.global_total ?? 0);
  const cacheHits = Number(m.cache_hits ?? 0);
  const tmHits = Number(m.tm_hits ?? 0);
  const reuseRate = Number(m.reuse_rate ?? 0);
  const duration = formatDuration(m.duration_s ?? m.dur_s);
  return `Ostatni run: ${step}/${status} | czas=${duration} | seg=${done}/${total} | cache=${cacheHits} | tm=${tmHits} | reuse=${reuseRate.toFixed(1)}%`;
}

function renderRunMetricsFromRuns(runs) {
  if (!runMetricsEl) return;
  const list = Array.isArray(runs) ? runs : [];
  if (!list.length) {
    runMetricsEl.textContent = 'Metryki runu: brak';
    return;
  }
  runMetricsEl.textContent = runMetricsText(list[0]);
}

function renderRunMetricsLive(stats) {
  if (!runMetricsEl) return;
  const s = stats || {};
  const done = Number(s.done || 0);
  const total = Number(s.total || 0);
  const cacheHits = Number(s.cache_hits || 0);
  const tmHits = Number(s.tm_hits || 0);
  const reuseRate = Number(s.reuse_rate || 0);
  const duration = formatDuration(s.dur_s);
  runMetricsEl.textContent = `Metryki runu: czas=${duration} | seg=${done}/${total} | cache=${cacheHits} | tm=${tmHits} | reuse=${reuseRate.toFixed(1)}%`;
}

function renderHistory(runs) {
  if (!historyEl) return;
  const list = Array.isArray(runs) ? runs : [];
  if (!list.length) {
    historyEl.textContent = 'Brak historii runow dla aktywnego projektu.';
    renderRunMetricsFromRuns([]);
    return;
  }
  historyEl.textContent = list.map((r) => {
    const started = formatTs(r.started_at);
    const step = r.step || '-';
    const status = normalizeStageStatus(r.status || 'none');
    const done = Number(r.metrics?.done ?? r.global_done ?? 0);
    const total = Number(r.metrics?.total ?? r.global_total ?? 0);
    const msg = r.message || '';
    return `[${started}] ${step} | ${status} | ${done}/${total} | ${msg}`;
  }).join('\n');
  renderRunMetricsFromRuns(list);
}

async function openExternal(url) {
  const u = String(url || '').trim();
  if (!u) return;
  try {
    if (window.desktopApi && typeof window.desktopApi.openExternal === 'function') {
      await window.desktopApi.openExternal(u);
      return;
    }
  } catch {}
  window.open(u, '_blank', 'noopener,noreferrer');
}

function renderModelList(models) {
  if (!modelEl) return;
  const list = Array.isArray(models) ? models : [];
  const current = String(val('model') || '').trim();
  modelEl.innerHTML = '';
  const placeholder = document.createElement('option');
  placeholder.value = '';
  placeholder.textContent = '-- wybierz model --';
  modelEl.appendChild(placeholder);
  for (const name of list) {
    const o = document.createElement('option');
    o.value = String(name);
    o.textContent = String(name);
    modelEl.appendChild(o);
  }
  if (current && list.includes(current)) setVal('model', current);
  else if (list.length) setVal('model', list[0]);
  else setVal('model', '');
}

function refillProfileSelect() {
  const current = selectedProfileId();
  profileSelectEl.innerHTML = '';
  const empty = document.createElement('option');
  empty.value = '';
  empty.textContent = '-- brak --';
  profileSelectEl.appendChild(empty);
  for (const p of profiles) {
    const o = document.createElement('option');
    o.value = String(p.id);
    o.textContent = p.name;
    profileSelectEl.appendChild(o);
  }
  if (current != null) profileSelectEl.value = String(current);
}

async function loadConfig() {
  try {
    const cfg = await api('/config');
    applyState(cfg);
    captureCurrentStep();
  } catch (e) {
    message(`Blad load config: ${e.message}`, true);
  }
}

async function saveConfig(notify = true) {
  try {
    await api('/config', { method: 'POST', body: JSON.stringify(collectState()) });
    if (notify) message('Config zapisany.');
    return true;
  } catch (e) {
    message(`Blad save config: ${e.message}`, true);
    return false;
  }
}

async function loadProfiles() {
  try {
    const data = await api('/profiles');
    profiles = Array.isArray(data.profiles) ? data.profiles : [];
    refillProfileSelect();
    applyStepToForm(currentMode());
  } catch (e) {
    message(`Blad profili: ${e.message}`, true);
  }
}

async function loadProjects(keepSelection = true) {
  try {
    const data = await api('/projects');
    const list = Array.isArray(data.projects) ? data.projects : [];
    const old = keepSelection ? currentProjectId : null;
    projectSelectEl.innerHTML = '';
    for (const p of list) {
      const o = document.createElement('option');
      o.value = String(p.id);
      const nameShort = shortText(p.name, 34);
      const summary = projectSummaryText(p);
      const st = normalizeProjectStatus(p.status || 'idle');
      o.textContent = `${nameShort} | ${st}/${p.active_step} | ${summary}`;
      o.title = `${p.name} | ${st}/${p.active_step} | ${summary}`;
      projectSelectEl.appendChild(o);
    }
    updateCounts(data.counts || {});
    if (!list.length) {
      currentProjectId = null;
      renderProjectSummary(null);
      renderHistory([]);
      renderRunMetricsFromRuns([]);
      return;
    }
    let next = null;
    if (old != null && list.some((p) => Number(p.id) === Number(old))) next = Number(old);
    if (next == null && data.active_project_id != null && list.some((p) => Number(p.id) === Number(data.active_project_id))) {
      next = Number(data.active_project_id);
    }
    if (next == null) next = Number(list[0].id);
    await selectProject(next, null, false);
  } catch (e) {
    message(`Blad projektow: ${e.message}`, true);
  }
}

function consumeProjectStepValues(project) {
  const sv = project?.step_values || {};
  stepValues = {
    translate: {
      output: String(sv.translate?.output || ''),
      prompt: String(sv.translate?.prompt || ''),
      cache: String(sv.translate?.cache || ''),
      profile_id: sv.translate?.profile_id == null ? null : Number(sv.translate.profile_id),
    },
    edit: {
      output: String(sv.edit?.output || ''),
      prompt: String(sv.edit?.prompt || ''),
      cache: String(sv.edit?.cache || ''),
      profile_id: sv.edit?.profile_id == null ? null : Number(sv.edit.profile_id),
    },
  };
}

async function selectProject(projectId, modeOverride = null, announce = true) {
  if (projectId == null) return;
  try {
    const body = { project_id: Number(projectId) };
    if (modeOverride) body.mode = modeNorm(modeOverride);
    const data = await api('/projects/select', { method: 'POST', body: JSON.stringify(body) });
    const project = data.project;
    currentProjectId = Number(project.id);
    projectSelectEl.value = String(currentProjectId);
    consumeProjectStepValues(project);
    renderProjectSummary(project);
    applyState(data.state || {});
    applyStepToForm(currentMode());
    renderHistory(data.runs || []);
    updateCounts(data.counts || {});
    if (announce) message(`Aktywny projekt: ${project.name}`);
  } catch (e) {
    message(`Blad wyboru projektu: ${e.message}`, true);
  }
}

async function saveProject(notify = true) {
  if (currentProjectId == null) {
    if (notify) message('Najpierw utworz lub wybierz projekt.', true);
    return false;
  }
  try {
    captureCurrentStep();
    const vals = {
      input_epub: String(val('input_epub') || ''),
      glossary_path: String(val('glossary') || ''),
      source_lang: String(val('source_lang') || '').toLowerCase(),
      target_lang: String(val('target_lang') || '').toLowerCase(),
      output_translate_epub: stepValues.translate.output || '',
      output_edit_epub: stepValues.edit.output || '',
      prompt_translate: stepValues.translate.prompt || '',
      prompt_edit: stepValues.edit.prompt || '',
      cache_translate_path: stepValues.translate.cache || '',
      cache_edit_path: stepValues.edit.cache || '',
      profile_translate_id: stepValues.translate.profile_id,
      profile_edit_id: stepValues.edit.profile_id,
      active_step: currentMode(),
    };
    const data = await api(`/projects/${currentProjectId}/save`, {
      method: 'POST',
      body: JSON.stringify({ values: vals }),
    });
    if (data.project) consumeProjectStepValues(data.project);
    if (notify) message('Projekt zapisany.');
    return true;
  } catch (e) {
    message(`Blad zapisu projektu: ${e.message}`, true);
    return false;
  }
}

async function createProject() {
  const name = String(val('new_project_name') || '').trim();
  const src = String(val('new_project_source') || '').trim();
  if (!name) {
    message('Podaj nazwe projektu.', true);
    return;
  }
  try {
    const data = await api('/projects/create', {
      method: 'POST',
      body: JSON.stringify({
        name,
        source_epub: src,
        source_lang: val('source_lang'),
        target_lang: val('target_lang'),
      }),
    });
    setVal('new_project_name', '');
    await loadProfiles();
    await loadProjects(false);
    if (data.project?.id != null) await selectProject(Number(data.project.id), null, false);
    message(`Utworzono projekt: ${name}`);
  } catch (e) {
    message(`Blad tworzenia projektu: ${e.message}`, true);
  }
}

async function deleteProject() {
  if (currentProjectId == null) {
    message('Brak aktywnego projektu.', true);
    return;
  }
  if (!window.confirm('Usunac aktywny projekt z listy?')) return;
  try {
    await api(`/projects/${currentProjectId}/delete`, { method: 'POST', body: JSON.stringify({ hard: false }) });
    currentProjectId = null;
    await loadProjects(false);
    message('Projekt usuniety z listy.');
  } catch (e) {
    message(`Blad usuwania projektu: ${e.message}`, true);
  }
}

async function saveProfile() {
  const name = String(val('new_profile_name') || '').trim();
  if (!name) {
    message('Podaj nazwe profilu.', true);
    return;
  }
  try {
    const data = await api('/profiles/create', {
      method: 'POST',
      body: JSON.stringify({ name, state: collectState() }),
    });
    setVal('new_profile_name', '');
    await loadProfiles();
    const pid = Number(data.profile?.id);
    if (Number.isFinite(pid)) {
      stepValues[currentMode()].profile_id = pid;
      profileSelectEl.value = String(pid);
    }
    message(`Profil zapisany: ${name}`);
  } catch (e) {
    message(`Blad zapisu profilu: ${e.message}`, true);
  }
}

async function applyProfile() {
  const pid = selectedProfileId();
  if (pid == null) {
    message('Wybierz profil.', true);
    return;
  }
  try {
    const data = await api(`/profiles/${pid}`);
    const settings = data.profile?.settings || {};
    for (const k of PROFILE_IDS) {
      if (Object.prototype.hasOwnProperty.call(settings, k)) setVal(k, settings[k]);
    }
    stepValues[currentMode()].profile_id = pid;
    message(`Wczytano profil: ${data.profile?.name || pid}`);
  } catch (e) {
    message(`Blad wczytywania profilu: ${e.message}`, true);
  }
}

async function refreshHistory() {
  if (currentProjectId == null) {
    renderHistory([]);
    return;
  }
  try {
    const data = await api(`/runs/recent?project_id=${encodeURIComponent(String(currentProjectId))}&limit=20`);
    renderHistory(data.runs || []);
  } catch (e) {
    historyEl.textContent = `Blad historii: ${e.message}`;
  }
}

async function queueCurrent() {
  if (!(await saveProject(false))) return;
  try {
    const data = await api('/queue/mark', {
      method: 'POST',
      body: JSON.stringify({ project_id: currentProjectId, step: currentMode() }),
    });
    updateCounts(data.counts || {});
    message(`Projekt zakolejkowany (${currentMode()}).`);
  } catch (e) {
    message(`Blad kolejki: ${e.message}`, true);
  }
}

async function runNextPending() {
  try {
    const data = await api('/queue/run-next', {
      method: 'POST',
      body: JSON.stringify({ state: collectState() }),
    });
    if (!data.ok) {
      message('Kolejka jest pusta.');
      return false;
    }
    if (data.project?.id != null) {
      await selectProject(Number(data.project.id), data.mode || data.project.active_step, false);
    } else {
      await refreshHistory();
    }
    message('Uruchomiono kolejny projekt z kolejki.');
    return true;
  } catch (e) {
    message(`Blad uruchamiania kolejki: ${e.message}`, true);
    return false;
  }
}

async function startRunAll() {
  runAllActive = true;
  setRunAllButtons();
  const started = await runNextPending();
  if (!started) {
    runAllActive = false;
    setRunAllButtons();
  }
}

function stopRunAll() {
  runAllActive = false;
  setRunAllButtons();
  message('Run-all zatrzymany po biezacym zadaniu.');
}

async function startRun() {
  if (!(await saveProject(false))) return;
  await saveConfig(false);
  try {
    await api('/run/start', { method: 'POST', body: JSON.stringify({ state: collectState() }) });
    message(`Start kroku: ${currentMode()}`);
  } catch (e) {
    message(`Blad start: ${e.message}`, true);
  }
}

async function validateRun() {
  const epub = String(val('output_epub') || val('input_epub') || '').trim();
  if (!epub) {
    message('Podaj output_epub lub input_epub.', true);
    return;
  }
  try {
    await api('/run/validate', {
      method: 'POST',
      body: JSON.stringify({
        epub_path: epub,
        tags: val('tags'),
        project_id: currentProjectId,
        tm_db: tmDbPath,
      }),
    });
    message('Start walidacji OK.');
  } catch (e) {
    message(`Blad walidacji: ${e.message}`, true);
  }
}

async function stopRun() {
  try {
    await api('/run/stop', { method: 'POST', body: '{}' });
    message('Stop wyslany.');
  } catch (e) {
    message(`Blad stop: ${e.message}`, true);
  }
}

async function fetchModels() {
  try {
    const provider = String(val('provider') || 'ollama');
    if (provider === 'ollama') {
      const data = await api(`/models/ollama?host=${encodeURIComponent(String(val('ollama_host') || ''))}`);
      renderModelList(data.models || []);
      message(`Modele ollama: ${data.models?.length || 0}`);
      return;
    }
    const key = String(val('google_api_key') || '');
    const data = await api(`/models/google?api_key=${encodeURIComponent(key)}`);
    renderModelList(data.models || []);
    message(`Modele google: ${data.models?.length || 0}`);
  } catch (e) {
    message(`Blad modeli: ${e.message}`, true);
  }
}

async function pollStatus() {
  try {
    const s = await api('/run/status');
    if (statusEl) statusEl.textContent = `Status: ${s.running ? 'RUNNING' : 'IDLE'} | mode=${s.mode} | exit=${s.exit_code ?? '--'}`;
    if (s.running && s.run_stats) {
      renderRunMetricsLive(s.run_stats);
    }
    if (logEl) {
      logEl.textContent = s.log || '';
      logEl.scrollTop = logEl.scrollHeight;
    }
    if (prevRunning && !s.running) {
      await refreshHistory();
    }
    if (runAllActive && prevRunning && !s.running && !runAllBusy) {
      runAllBusy = true;
      const started = await runNextPending();
      if (!started) {
        runAllActive = false;
        setRunAllButtons();
      }
      runAllBusy = false;
    }
    prevRunning = !!s.running;
  } catch (e) {
    if (statusEl) statusEl.textContent = `Status: backend offline (${e.message})`;
  }
}

async function pickOpenFile(filters = []) {
  try {
    if (window.desktopApi && typeof window.desktopApi.pickFile === 'function') {
      return await window.desktopApi.pickFile({ filters });
    }
  } catch {}
  return '';
}

async function pickSaveFile(defaultPath = '', filters = []) {
  try {
    if (window.desktopApi && typeof window.desktopApi.pickSaveFile === 'function') {
      return await window.desktopApi.pickSaveFile({ defaultPath, filters });
    }
  } catch {}
  return '';
}

async function pickIntoField(fieldId, save = false, filters = []) {
  const current = String(val(fieldId) || '');
  const path = save ? await pickSaveFile(current, filters) : await pickOpenFile(filters);
  if (path) setVal(fieldId, path);
}

function bindEvents() {
  const bind = (id, fn) => {
    const el = document.getElementById(id);
    if (el) el.addEventListener('click', fn);
  };
  bind('support-link', () => openExternal(SUPPORT_URL));
  bind('repo-link', () => openExternal(REPO_URL));
  bind('copy-setup-btn', copySetupGuide);

  bind('save-config-btn', () => saveConfig(true));
  bind('models-btn', fetchModels);
  bind('start-btn', startRun);
  bind('validate-btn', validateRun);
  bind('stop-btn', stopRun);

  bind('refresh-projects-btn', () => loadProjects(true));
  bind('create-project-btn', createProject);
  bind('save-project-btn', () => saveProject(true));
  bind('delete-project-btn', deleteProject);
  bind('save-profile-btn', saveProfile);
  bind('apply-profile-btn', applyProfile);

  bind('queue-btn', queueCurrent);
  bind('run-next-btn', async () => { await runNextPending(); });
  bind('run-all-btn', startRunAll);
  bind('stop-run-all-btn', stopRunAll);

  if (projectSelectEl) {
    projectSelectEl.addEventListener('change', async () => {
      const raw = String(projectSelectEl.value || '').trim();
      if (!raw) return;
      await selectProject(Number(raw), null, true);
    });
  }

  if (modeEl) {
    modeEl.addEventListener('change', async () => {
      if (suppressModeEvent) return;
      const nextMode = modeNorm(String(modeEl.value || 'translate'));
      captureCurrentStep();
      if (currentProjectId != null) {
        await saveProject(false);
        await selectProject(currentProjectId, nextMode, false);
      } else {
        applyStepToForm(nextMode);
      }
    });
  }

  if (profileSelectEl) {
    profileSelectEl.addEventListener('change', () => {
      stepValues[currentMode()].profile_id = selectedProfileId();
    });
  }

  bind('pick_new_project_source_btn', async () => {
    await pickIntoField('new_project_source', false, [{ name: 'EPUB', extensions: ['epub'] }]);
  });
  bind('pick_input_epub_btn', async () => {
    await pickIntoField('input_epub', false, [{ name: 'EPUB', extensions: ['epub'] }]);
  });
  bind('pick_output_epub_btn', async () => {
    await pickIntoField('output_epub', true, [{ name: 'EPUB', extensions: ['epub'] }]);
  });
  bind('pick_prompt_btn', async () => {
    await pickIntoField('prompt', false, [{ name: 'TXT', extensions: ['txt'] }]);
  });
  bind('pick_glossary_btn', async () => {
    await pickIntoField('glossary', false, [{ name: 'Text', extensions: ['txt', 'csv', 'json', 'jsonl'] }]);
  });
  bind('pick_cache_btn', async () => {
    await pickIntoField('cache', true, [{ name: 'JSONL', extensions: ['jsonl', 'json'] }]);
  });
}

async function init() {
  try {
    renderSetupGuide();
    bindEvents();
    setRunAllButtons();
    await loadConfig();
    await loadProfiles();
    await loadProjects(false);
    await refreshHistory();
    await fetchModels();
    await pollStatus();
    setInterval(pollStatus, 1200);
  } catch (e) {
    message(`Blad inicjalizacji UI: ${e.message || e}`, true);
  }
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', () => {
    init();
  }, { once: true });
} else {
  init();
}
