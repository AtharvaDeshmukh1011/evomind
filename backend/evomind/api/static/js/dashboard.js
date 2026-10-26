const form = document.getElementById('analyzeForm');
const btn = document.getElementById('analyzeBtn');
const btnLabel = btn.querySelector('.btn-label');
const statusLine = document.getElementById('statusLine');
const results = document.getElementById('results');
const emptyState = document.getElementById('emptyState');
const sidebar = document.getElementById('sidebar');
let currentRepo = null;
let lastData = null;

const STATUS_BANDS = [
  { min: 0.66, label: 'Critical', pill: 'neg' },
  { min: 0.50, label: 'Serious',  pill: 'warn' },
  { min: 0.33, label: 'Watch',    pill: '' },
  { min: 0,    label: 'Low',      pill: 'pos' },
];
function bandFor(score) {
  return STATUS_BANDS.find(b => score >= b.min);
}
function bandPill(score) {
  const b = bandFor(score);
  return `<span class="pill ${b.pill}">${b.label}</span>`;
}

const VIEWS = ['risk', 'architecture', 'model', 'pull-requests'];
function currentView() {
  const v = location.hash.slice(1);
  return VIEWS.includes(v) ? v : 'risk';
}
function showView() {
  const view = currentView();
  document.querySelectorAll('[data-view-panel]').forEach(el => { el.hidden = el.dataset.viewPanel !== view; });
  document.querySelectorAll('.nav-item[data-view]').forEach(a => {
    if (a.dataset.view === view) a.setAttribute('aria-current', 'page'); else a.removeAttribute('aria-current');
  });
  sidebar.classList.remove('open');
}
window.addEventListener('hashchange', () => {
  window.scrollTo(0, 0);
  document.dispatchEvent(new CustomEvent('evo:view'));
  if (document.startViewTransition && !matchMedia('(prefers-reduced-motion: reduce)').matches) document.startViewTransition(showView);
  else showView();
});
showView();

document.getElementById('menuToggle').addEventListener('click', () => sidebar.classList.add('open'));
document.getElementById('menuClose').addEventListener('click', () => sidebar.classList.remove('open'));

const themeLabel = document.getElementById('themeLabel');
function effectiveTheme() {
  return document.documentElement.getAttribute('data-theme') || 'dark';
}
const frontTheme = document.getElementById('frontTheme');
function syncThemeLabel() {
  const next = effectiveTheme() === 'dark' ? 'Light theme' : 'Dark theme';
  themeLabel.textContent = next;
  frontTheme.setAttribute('aria-label', `Switch to ${next.toLowerCase()}`);
}
function flipTheme() {
  const next = effectiveTheme() === 'dark' ? 'light' : 'dark';
  document.documentElement.setAttribute('data-theme', next);
  try { localStorage.setItem('evomind-theme', next); } catch {}
  syncThemeLabel();
}
document.getElementById('themeToggle').addEventListener('click', flipTheme);
frontTheme.addEventListener('click', flipTheme);
syncThemeLabel();

const optionsBtn = document.getElementById('optionsBtn');
const optionsPanel = document.getElementById('optionsPanel');
function setOptions(open) {
  optionsPanel.hidden = !open;
  optionsBtn.setAttribute('aria-expanded', String(open));
}
optionsBtn.addEventListener('click', () => setOptions(optionsPanel.hidden));
document.addEventListener('keydown', (e) => {
  if (e.key !== 'Escape') return;
  setOptions(false);
  closeRecommendation();
  sidebar.classList.remove('open');
});

function selectAllOnFocus(el) {
  el.addEventListener('focus', () => el.select());
  el.addEventListener('mouseup', (e) => {
    if (document.activeElement === el) e.preventDefault();
  });
}
['repo', 'horizon', 'trainFraction'].forEach(id => selectAllOnFocus(document.getElementById(id)));

document.querySelectorAll('[data-repo]').forEach(b => b.addEventListener('click', () => {
  const input = document.getElementById('repo');
  input.value = b.dataset.repo;
  input.focus();
}));

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
}
function displayPath(p) {
  return String(p).replace(/\\/g, '/');
}
function fmtDate(iso) {
  return new Date(iso).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' });
}
function repoName(repo) {
  const s = String(repo).replace(/\.git$/, '').replace(/[\\/]+$/, '');
  const m = s.match(/github\.com[/:]([^/]+\/[^/]+)$/);
  if (m) return m[1];
  return s.split(/[\\/]/).slice(-2).join('/');
}
function formatValue(v) {
  return Number.isInteger(v) ? v.toLocaleString() : v.toFixed(1);
}
function plural(n, word) {
  return `${n} ${word}${n === 1 ? '' : 's'}`;
}

const progressPanel = document.getElementById('progressPanel');
const progressSteps = document.getElementById('progressSteps');
const progressElapsedEl = document.getElementById('progressElapsed');
let progressStartTime = null;
let progressTimerId = null;

function resetProgress() {
  progressSteps.innerHTML = '';
  progressStartTime = Date.now();
  updateElapsed();
  if (progressTimerId) clearInterval(progressTimerId);
  progressTimerId = setInterval(updateElapsed, 1000);
  progressPanel.hidden = false;
}
function updateElapsed() {
  const secs = Math.floor((Date.now() - progressStartTime) / 1000);
  progressElapsedEl.textContent = secs < 60 ? `${secs}s` : `${Math.floor(secs / 60)}m ${secs % 60}s`;
}
function markLastStepDone() {
  const prev = progressSteps.lastElementChild;
  if (prev && prev.classList.contains('active')) {
    prev.classList.remove('active');
    prev.classList.add('done');
    prev.querySelector('.state').textContent = '✓';
  }
}
function addProgressStep(message) {
  markLastStepDone();
  const li = document.createElement('li');
  li.className = 'active';
  li.innerHTML = '<span class="state"><span class="spinner" aria-hidden="true"></span></span><span></span>';
  li.lastElementChild.textContent = message;
  progressSteps.appendChild(li);
}
function finishProgress() {
  if (progressTimerId) { clearInterval(progressTimerId); progressTimerId = null; }
  markLastStepDone();
  progressPanel.hidden = true;
}

function showError(message) {
  statusLine.textContent = message;
  statusLine.hidden = false;
}

const STATIC = !!window.EVOMIND_STATIC;
const SAVED_REPOS = ['pallets/click', 'pallets/flask', 'psf/requests', 'django/django'];
const REPLAY_STEPS = [
  'Cloning repository…', 'Mining commit history…', 'Reading code at the training cutoff…',
  "Reading the repository's current state…", 'Computing code metrics and building features…',
  'Tracing bug-inducing commits (SZZ)…', 'Reading earlier snapshots for risk trends…',
  'Training Random Forest and Logistic Regression models…', "Scoring the repository's current files…",
  'Computing risk trends…', 'Building the dependency graph…', 'Done.',
];
const LIVE_ONLY = 'the live version of EvoMind. Run it locally to use this.';

function savedFile(repo) {
  const slug = repoName(repo).toLowerCase();
  if (!SAVED_REPOS.includes(slug)) return null;
  return slug === 'pallets/click' ? '/static/sample-analysis.json' : `/static/samples/${slug.replace('/', '__')}.json`;
}

function replaySaved(repo) {
  const handlers = {};
  const fake = { closed: false, addEventListener(type, fn) { (handlers[type] = handlers[type] || []).push(fn); }, close() { fake.closed = true; } };
  const emit = (type, payload) => { if (!fake.closed) (handlers[type] || []).forEach(fn => fn({ data: JSON.stringify(payload) })); };
  setTimeout(async () => {
    const file = savedFile(repo);
    if (!file) {
      emit('error', { detail: `This online demo shows saved analyses only (${SAVED_REPOS.join(', ')}). Run EvoMind locally to scan any repository.` });
      return;
    }
    let data;
    try { data = await (await fetch(file)).json(); } catch (_) { emit('error', { detail: 'The saved analysis could not be loaded.' }); return; }
    for (const step of REPLAY_STEPS) {
      emit('progress', { message: step });
      await new Promise(r => setTimeout(r, 900));
    }
    emit('result', data);
  }, 300);
  return fake;
}

if (STATIC) {
  const docs = document.querySelector('a[href="/docs"]');
  if (docs) docs.hidden = true;
  const note = document.getElementById('staticNote');
  if (note) note.hidden = false;
}

form.addEventListener('submit', (e) => {
  e.preventDefault();
  const repo = document.getElementById('repo').value.trim();
  const horizon_days = parseInt(document.getElementById('horizon').value, 10);
  const train_fraction = parseFloat(document.getElementById('trainFraction').value);
  const use_llm_szz = document.getElementById('useLlmSzz').checked;
  if (!repo) return;

  if (currentView() !== 'risk') history.replaceState(null, '', '#risk');
  showView();
  window.scrollTo(0, 0);
  document.dispatchEvent(new CustomEvent('evo:view'));
  setOptions(false);
  btn.disabled = true;
  btnLabel.textContent = 'Analyzing…';
  statusLine.hidden = true;
  results.hidden = true;
  emptyState.hidden = true;
  document.getElementById('pageTitle').textContent = repoName(repo);
  document.getElementById('pageSub').textContent = 'Analysis in progress.';
  document.getElementById('stamp').textContent = '';
  resetProgress();

  const params = new URLSearchParams({ repo, horizon_days, train_fraction, top_n: 30, use_llm_szz });
  const es = STATIC ? replaySaved(repo) : new EventSource(`/analyze/stream?${params.toString()}`);

  es.addEventListener('progress', (ev) => {
    const message = JSON.parse(ev.data).message;
    addProgressStep(message);
    document.dispatchEvent(new CustomEvent('evo:progress', { detail: message }));
  });

  es.addEventListener('queue', (ev) => {
    const message = JSON.parse(ev.data).message;
    document.getElementById('pageSub').textContent = message;
    document.dispatchEvent(new CustomEvent('evo:queue', { detail: message }));
  });

  es.addEventListener('result', (ev) => {
    const data = JSON.parse(ev.data);
    finishProgress();
    currentRepo = repo;
    render(data);
    document.dispatchEvent(new CustomEvent('evo:result', { detail: data }));
    document.getElementById('stamp').textContent = `Analysed ${new Date().toLocaleString('en-GB', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })}`;
    btn.disabled = false;
    btnLabel.textContent = 'Analyze';
    es.close();
  });

  es.addEventListener('error', (ev) => {
    finishProgress();
    let message = 'Analysis failed: the connection to the server was lost. Check that the EvoMind server is running, then try again.';
    if (ev.data) {
      try { message = JSON.parse(ev.data).detail || message; } catch (_) {}
    }
    showError(message);
    document.dispatchEvent(new CustomEvent('evo:error', { detail: message }));
    results.hidden = !lastData;
    emptyState.hidden = !!lastData;
    if (lastData) renderTitle(lastData);
    btn.disabled = false;
    btnLabel.textContent = 'Analyze';
    es.close();
  });
});

let riskFilesData = [];
let riskSort = { key: 'risk_score', dir: 'desc' };
let riskFilter = '';

let coupledFilesData = [];
let couplingSort = { key: 'afferent', dir: 'desc' };
let couplingFilter = '';

function renderTitle(data) {
  document.getElementById('pageTitle').textContent = repoName(data.repo || currentRepo || '');
  document.getElementById('pageSub').textContent =
    `Chance that each file needs a bug fix within ${data.horizon_days} days, and why.`;
}

function render(data) {
  lastData = data;
  emptyState.hidden = true;
  statusLine.hidden = true;
  results.hidden = false;
  renderTitle(data);
  renderHistory(data);

  const top = data.top_risk_files[0];
  document.getElementById('statTopRisk').textContent = top ? top.risk_score.toFixed(2) : '—';
  document.getElementById('statTopRisk').style.color = !top ? '' : top.risk_score >= 0.66 ? 'var(--negative)' : top.risk_score >= 0.5 ? 'var(--warning)' : 'var(--positive)';
  document.getElementById('statTopRiskFile').textContent = top ? displayPath(top.file_path) : 'No files scored';
  document.getElementById('statTopRiskFile').title = top ? displayPath(top.file_path) : '';

  const withTrend = data.top_risk_files.filter(f => f.trend_delta !== null && f.trend_delta !== undefined);
  const rising = withTrend.filter(f => f.trend_delta > 0.02).length;
  document.getElementById('statRising').innerHTML = withTrend.length ? `${rising}<small>of ${withTrend.length}</small>` : '—';
  document.getElementById('statRising').style.color = rising ? 'var(--warning)' : 'var(--positive)';
  document.getElementById('statRisingSub').textContent = withTrend.length ? 'up more than 0.02 since first scored' : 'Not enough history for a trend';

  document.getElementById('statPositiveRate').textContent = `${(data.training_positive_rate * 100).toFixed(1)}%`;
  document.getElementById('statFiles').textContent = `of ${data.training_files} files, cutoff ${fmtDate(data.cutoff)}`;

  const best = data.evaluation.find(r => r.model_name === data.best_model) || data.evaluation[0];
  document.getElementById('statBestScore').textContent = best && Number.isFinite(best.roc_auc) ? best.roc_auc.toFixed(3) : 'n/a';
  document.getElementById('statBestScore').style.color = !best || !Number.isFinite(best.roc_auc) ? '' : best.roc_auc >= 0.8 ? 'var(--positive)' : best.roc_auc >= 0.7 ? 'var(--accent-2)' : 'var(--warning)';
  document.getElementById('statBestModel').textContent = MODEL_LABEL[data.best_model] || data.best_model;

  const llmSzzNote = document.getElementById('llmSzzNote');
  if (data.llm_szz_assessed !== null && data.llm_szz_assessed !== undefined) {
    const total = data.llm_szz_assessed + data.llm_szz_fallback;
    llmSzzNote.hidden = false;
    if (data.llm_szz_assessed === 0 && data.llm_szz_fallback > 0) {
      llmSzzNote.textContent = `LLM-assisted SZZ was requested, but all ${plural(data.llm_szz_fallback, 'candidate')} fell back to plain SZZ. Check that GROQ_API_KEY is set on the server.`;
    } else {
      llmSzzNote.textContent = `LLM-assisted SZZ assessed ${data.llm_szz_assessed} of ${plural(total, 'candidate')}` +
        (data.llm_szz_fallback ? `; ${data.llm_szz_fallback} fell back to plain SZZ.` : '.');
    }
  } else {
    llmSzzNote.hidden = true;
  }

  renderMetricTable(data.evaluation, data.best_model);
  renderFeatureImportance(data.feature_importances, data.feature_importance_kind);

  riskFilesData = data.top_risk_files.map((f, i) => ({ ...f, originalRank: i + 1 }));
  riskFilter = '';
  document.getElementById('riskSearch').value = '';
  applyRiskView();
  document.getElementById('navRiskCount').textContent = riskFilesData.length || '';

  coupledFilesData = data.most_coupled_files;
  couplingFilter = '';
  document.getElementById('couplingSearch').value = '';
  document.getElementById('depEdgeCount').textContent = data.dependency_edge_count;
  applyCouplingView();
  renderCycles(data.cyclic_groups);

  roResults.innerHTML = '';
  prResult.innerHTML = '';
  prStatus.hidden = true;
  showView();
  document.dispatchEvent(new CustomEvent('evo:data', { detail: data }));
}

function renderHistory(data) {
  const el = document.getElementById('history');
  const cutoff = new Date(data.cutoff).getTime();
  const windowEndRaw = cutoff + data.horizon_days * 86400000;
  if (!data.history_start || !data.history_end) {
    el.innerHTML = `<ul class="history-legend"><li><span class="key seg-train"></span><b>Learned from history up to ${fmtDate(data.cutoff)}</b><span class="when">${data.training_files} files, labelled by bug fixes in the next ${data.horizon_days} days</span></li></ul>`;
    return;
  }
  const start = new Date(data.history_start).getTime();
  const end = new Date(data.history_end).getTime();
  const windowEnd = Math.min(windowEndRaw, end);
  const total = Math.max(end - start, 1);
  const share = v => Math.max(v / total, 0);
  const years = (end - start) / (365.25 * 86400000);
  el.innerHTML = `
    <div class="history-bar" role="img" aria-label="History from ${fmtDate(start)} to ${fmtDate(end)}; trained up to ${fmtDate(cutoff)}">
      <span class="seg-train" style="flex-grow:${share(cutoff - start)}"></span>
      <span class="seg-window" style="flex-grow:${share(windowEnd - cutoff)}"></span>
      <span class="seg-after" style="flex-grow:${share(end - windowEnd)}"></span>
    </div>
    <ul class="history-legend">
      <li><span class="key seg-train"></span><b>Learned from ${years >= 2 ? Math.round(years) + ' years' : 'the history'} of commits</b><span class="when num">${fmtDate(start)} – ${fmtDate(cutoff)} · ${data.training_files} files</span></li>
      <li><span class="key seg-window"></span><b>Labelled by fixes in the next ${data.horizon_days} days</b><span class="when num">${fmtDate(cutoff)} – ${fmtDate(windowEnd)}</span></li>
      <li><span class="key seg-after"></span><b>Scored at the latest commit</b><span class="when num">${fmtDate(end)} · ${data.top_risk_files.length} riskiest shown</span></li>
    </ul>`;
}

const MODEL_LABEL = { random_forest: 'Random Forest', logistic_regression_baseline: 'Logistic Regression' };

function renderMetricTable(evaluation, bestModel) {
  const rows = [...evaluation].sort((a, b) => (a.model_name === bestModel ? -1 : b.model_name === bestModel ? 1 : 0));
  const fmt = v => Number.isFinite(v) ? v.toFixed(3) : 'n/a';
  document.querySelector('#metricTable tbody').innerHTML = rows.map(r => `<tr>
      <td>${escapeHtml(MODEL_LABEL[r.model_name] || r.model_name)}${r.model_name === bestModel ? ' <span class="pill" style="margin-left:8px">Selected</span>' : ''}</td>
      <td class="n">${fmt(r.precision)}</td>
      <td class="n">${fmt(r.recall)}</td>
      <td class="n">${fmt(r.f1)}</td>
      <td class="n">${fmt(r.roc_auc)}</td>
      <td class="n">${fmt(r.average_precision)}</td>
    </tr>`).join('');
}

function renderFeatureImportance(importances, kind) {
  document.getElementById('featureImportanceDesc').textContent =
    kind ? `Feature importances, ${kind}.` : 'Feature importances from the selected model.';
  const entries = Object.entries(importances).slice(0, 8);
  const max = Math.max(...entries.map(([, v]) => v), 0.001);
  document.getElementById('featureImportance').innerHTML = entries.length ? entries.map(([name, val]) => `
    <div class="bar-row">
      <span>${escapeHtml(name)}</span>
      <span class="track"><i style="width:${Math.max(2, (val / max) * 100)}%"></i></span>
      <span class="num">${val.toFixed(3)}</span>
    </div>`).join('') : '<p class="muted">No importances reported.</p>';
}

function sortRows(rows, key, dir) {
  return [...rows].sort((a, b) => {
    const av = a[key], bv = b[key];
    if (av === null || av === undefined) return (bv === null || bv === undefined) ? 0 : 1;
    if (bv === null || bv === undefined) return -1;
    const cmp = typeof av === 'string' ? av.localeCompare(bv) : av - bv;
    return dir === 'asc' ? cmp : -cmp;
  });
}

function wireSortableHeaders(theadEl, state, applyFn) {
  theadEl.querySelectorAll('th[data-sort]').forEach(th => {
    th.querySelector('.sort').addEventListener('click', () => {
      const key = th.dataset.sort;
      if (state.key === key) {
        state.dir = state.dir === 'asc' ? 'desc' : 'asc';
      } else {
        state.key = key;
        state.dir = th.dataset.sortDefault || 'desc';
      }
      theadEl.querySelectorAll('th[data-sort]').forEach(h => h.removeAttribute('aria-sort'));
      th.setAttribute('aria-sort', state.dir === 'asc' ? 'ascending' : 'descending');
      applyFn();
    });
  });
}
wireSortableHeaders(document.getElementById('riskTableHead'), riskSort, applyRiskView);
wireSortableHeaders(document.getElementById('couplingTableHead'), couplingSort, applyCouplingView);

document.getElementById('riskSearch').addEventListener('input', (e) => {
  riskFilter = e.target.value.trim().toLowerCase();
  applyRiskView();
});
document.getElementById('couplingSearch').addEventListener('input', (e) => {
  couplingFilter = e.target.value.trim().toLowerCase();
  applyCouplingView();
});

function matches(path, filter) {
  return displayPath(path).toLowerCase().includes(filter.replace(/\\/g, '/'));
}

function applyRiskView() {
  let rows = riskFilesData;
  if (riskFilter) rows = rows.filter(f => matches(f.file_path, riskFilter));
  rows = sortRows(rows, riskSort.key, riskSort.dir);
  document.getElementById('riskRowCount').textContent =
    riskFilesData.length ? (riskFilter ? `${rows.length} of ${riskFilesData.length} files` : plural(riskFilesData.length, 'file')) : '';
  renderRiskTable(rows);
}

function applyCouplingView() {
  let rows = coupledFilesData;
  if (couplingFilter) rows = rows.filter(f => matches(f.file_path, couplingFilter));
  rows = sortRows(rows, couplingSort.key, couplingSort.dir);
  document.getElementById('couplingRowCount').textContent =
    coupledFilesData.length ? (couplingFilter ? `${rows.length} of ${coupledFilesData.length} files` : plural(coupledFilesData.length, 'file')) : '';
  renderCoupling(rows);
}

function renderReasons(reasons) {
  if (!reasons || !reasons.length) return '';
  return `<ul class="reasons">${reasons.map(r => {
    const top = Math.max(1, Math.round((1 - r.percentile) * 100));
    return `<li><span>${escapeHtml(r.label)}</span><span class="v num">${formatValue(r.value)}</span>` +
      `<span>top ${top}%</span><span class="imp num" title="If this were typical for the repository, risk would fall by ${r.impact.toFixed(3)}">+${r.impact.toFixed(2)} risk</span></li>`;
  }).join('')}</ul>`;
}

function renderTrend(points, delta) {
  const known = (points || []).map((p, i) => ({ i, r: p.risk, d: p.date })).filter(p => p.r !== null && p.r !== undefined);
  if (known.length < 2 || delta === null || delta === undefined) return '<span class="muted">New</span>';
  const W = 72, H = 22, n = points.length - 1;
  const x = i => 2 + (i / n) * (W - 4);
  const y = r => H - 2 - r * (H - 4);
  const rising = delta > 0.02, falling = delta < -0.02;
  const cls = rising ? 'up' : falling ? 'down' : 'muted';
  const line = known.map(p => `${x(p.i).toFixed(1)},${y(p.r).toFixed(1)}`).join(' ');
  const last = known[known.length - 1];
  const tip = known.map(p => `${p.d}: ${p.r.toFixed(2)}`).join('&#10;');
  const sign = delta > 0 ? '+' : delta < 0 ? '−' : '';
  return `<span class="trend ${cls}" title="${tip}">` +
    `<svg width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" aria-hidden="true">` +
    `<line x1="2" x2="${W - 2}" y1="${y(0.5)}" y2="${y(0.5)}" stroke="var(--border)" stroke-dasharray="2 3"/>` +
    `<polyline points="${line}" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round" stroke-linecap="round"/>` +
    `<circle cx="${x(last.i)}" cy="${y(last.r)}" r="2.4" fill="currentColor"/></svg>` +
    `<span class="trend-delta num">${sign}${Math.abs(delta).toFixed(2)}</span></span>`;
}

function renderRiskTable(files) {
  const tbody = document.getElementById('riskTableBody');
  if (!files.length) {
    tbody.innerHTML = `<tr><td colspan="6" class="empty-cell">${riskFilesData.length ? 'No files match that filter.' : 'No files were scored.'}</td></tr>`;
    return;
  }
  tbody.innerHTML = files.map(f => `<tr>
      <td class="rank n num">${f.originalRank}</td>
      <td class="file"><div class="path">${escapeHtml(displayPath(f.file_path))}</div>${renderReasons(f.reasons)}</td>
      <td class="band">${bandPill(f.risk_score)}</td>
      <td class="n score-cell"><span class="score"><span class="meter"><i style="width:${Math.max(2, f.risk_score * 100)}%"></i></span><span class="num">${f.risk_score.toFixed(3)}</span></span></td>
      <td class="n trend-cell">${renderTrend(f.trend, f.trend_delta)}</td>
      <td class="ask"><button class="btn small ai-btn" type="button" data-file="${escapeHtml(f.file_path)}">Ask AI</button></td>
    </tr>`).join('');
  tbody.querySelectorAll('.ai-btn').forEach(el => {
    el.addEventListener('click', () => openRecommendation(el.dataset.file));
  });
}

function renderCoupling(files) {
  const tbody = document.getElementById('couplingTableBody');
  if (!files.length) {
    tbody.innerHTML = `<tr><td colspan="4" class="empty-cell">${coupledFilesData.length ? 'No files match that filter.' : 'No imports between files of this repository were found.'}</td></tr>`;
    return;
  }
  tbody.innerHTML = files.map(f => `<tr>
      <td><div class="path">${escapeHtml(displayPath(f.file_path))}</div></td>
      <td class="n num">${f.afferent}</td>
      <td class="n num">${f.efferent}</td>
      <td class="n"><span class="score"><span class="meter"><i style="width:${Math.max(2, f.instability * 100)}%"></i></span><span class="num">${f.instability.toFixed(2)}</span></span></td>
    </tr>`).join('');
}

function renderCycles(cyclicGroups) {
  const list = document.getElementById('cyclesList');
  document.getElementById('navCycleCount').textContent = cyclicGroups && cyclicGroups.length ? cyclicGroups.length : '';
  if (cyclicGroups && cyclicGroups.length) {
    list.innerHTML = cyclicGroups.map((group, g) => `<li class="cycle-card">
        <div class="cycle-head"><h3>Loop ${g + 1}</h3><span class="pill neg">${plural(group.length, 'file')}</span></div>
        ${cycleRing(group.length)}
        <ol class="cycle-files">${group.map((f, i) => `<li data-i="${i}"><b>${i + 1}</b><span>${escapeHtml(displayPath(f))}</span></li>`).join('')}</ol>
      </li>`).join('');
  } else {
    list.innerHTML = '<li class="muted">No circular imports found.</li>';
  }
}

function cycleRing(n) {
  const S = 180, c = S / 2, r = 64, nodeR = n > 8 ? 10 : 13;
  const pts = Array.from({ length: n }, (_, i) => {
    const a = -Math.PI / 2 + i * 2 * Math.PI / n;
    return [c + r * Math.cos(a), c + r * Math.sin(a)];
  });
  const path = `M ${c} ${c - r} A ${r} ${r} 0 1 1 ${c - 0.01} ${c - r} Z`;
  return `<svg viewBox="0 0 ${S} ${S}" width="${S}" height="${S}" aria-hidden="true">
    <circle class="ring-track" cx="${c}" cy="${c}" r="${r}"/>
    <circle class="ring-flow" cx="${c}" cy="${c}" r="${r}"/>
    <circle class="ring-dot" r="4"><animateMotion dur="${(2 + n * 0.35).toFixed(1)}s" repeatCount="indefinite" path="${path}"/></circle>
    ${pts.map(([x, y], i) => `<g class="ring-node" data-i="${i}"><circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="${nodeR}"/><text x="${x.toFixed(1)}" y="${(y + 4).toFixed(1)}">${i + 1}</text></g>`).join('')}
  </svg>`;
}
const cyclesListEl = document.getElementById('cyclesList');
cyclesListEl.addEventListener('mouseover', (e) => {
  const card = e.target.closest('.cycle-card');
  if (!card) return;
  const hit = e.target.closest('[data-i]');
  card.querySelectorAll('[data-i]').forEach(el => el.classList.toggle('on', !!hit && el.dataset.i === hit.dataset.i));
});
cyclesListEl.addEventListener('mouseleave', () => cyclesListEl.querySelectorAll('.on').forEach(el => el.classList.remove('on')));

const recModal = document.getElementById('recModal');
const recBody = document.getElementById('recBody');
const recFilePath = document.getElementById('recFilePath');
let recReturnFocus = null;

document.getElementById('recClose').addEventListener('click', closeRecommendation);
recModal.addEventListener('click', (e) => { if (e.target === recModal) closeRecommendation(); });

function closeRecommendation() {
  if (recModal.hidden) return;
  recModal.hidden = true;
  if (recReturnFocus) recReturnFocus.focus();
}

const PRIORITY_PILL = { high: 'neg', medium: 'warn', low: '' };

async function openRecommendation(filePath) {
  if (STATIC) {
    recReturnFocus = document.activeElement;
    recFilePath.textContent = displayPath(filePath);
    recBody.innerHTML = `<p class="muted">AI recommendations need ${LIVE_ONLY}</p>`;
    recModal.hidden = false;
    document.getElementById('recClose').focus();
    return;
  }
  recReturnFocus = document.activeElement;
  recFilePath.textContent = displayPath(filePath);
  recBody.innerHTML = '<p class="status-text"><span class="spinner" aria-hidden="true"></span>Asking the model for a recommendation…</p>';
  recModal.hidden = false;
  document.getElementById('recClose').focus();

  try {
    const res = await fetch('/recommend', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ repo: currentRepo, file_path: filePath }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Recommendation failed.');
    const suggestions = data.suggestions.length
      ? data.suggestions.map(s => `<div class="suggestion">
          <div class="head"><span class="pill ${PRIORITY_PILL[s.priority] ?? ''}">${escapeHtml(s.priority)}</span>${escapeHtml(s.issue)}</div>
          <p>${escapeHtml(s.recommendation)}</p>
        </div>`).join('')
      : '<p class="muted">The model did not flag any concrete issues.</p>';
    recBody.innerHTML = `<p class="summary">${escapeHtml(data.summary)}</p>${suggestions}`;
  } catch (err) {
    recBody.innerHTML = `<p class="error-text">${escapeHtml(err.message)}</p>`;
  }
}

const prBtn = document.getElementById('prBtn');
const prBtnLabel = prBtn.querySelector('.pr-btn-label');
const prStatus = document.getElementById('prStatus');
const prResult = document.getElementById('prResult');

function trendText(delta) {
  if (delta === null || delta === undefined) return '<span class="muted">—</span>';
  if (delta > 0.02) return `<span class="up num">+${delta.toFixed(2)}</span>`;
  if (delta < -0.02) return `<span class="down num">−${Math.abs(delta).toFixed(2)}</span>`;
  return '<span class="muted">Steady</span>';
}

function renderPrReport(data) {
  const scored = data.files.filter(f => f.risk_score !== null);
  const unscored = data.files.filter(f => f.risk_score === null);
  const high = data.high_risk_count;
  const headline = high
    ? `This pull request touches <b>${plural(high, 'high-risk file')}</b> (Serious or above). Worth a careful review.`
    : scored.length ? 'No high-risk files touched.' : 'None of the changed files could be scored.';
  const rows = scored.map(f => `<tr>
      <td><div class="path">${escapeHtml(displayPath(f.path))}</div>${renderReasons(f.reasons)}</td>
      <td>${bandPill(f.risk_score)}</td>
      <td class="n">${trendText(f.trend_delta)}</td>
      <td class="n"><span class="score"><span class="meter"><i style="width:${Math.max(2, f.risk_score * 100)}%"></i></span><span class="num">${f.risk_score.toFixed(3)}</span></span></td>
    </tr>`).join('');
  const table = scored.length ? `<div class="table-wrap"><table><thead><tr><th>Changed file</th><th>Band</th><th class="n">Trend</th><th class="n">Risk</th></tr></thead><tbody>${rows}</tbody></table></div>` : '';
  const rest = unscored.length
    ? `<div class="unscored"><h3>Not scored</h3><ul>${unscored.map(f => `<li><code>${escapeHtml(displayPath(f.path))}</code> · ${escapeHtml(f.note)}</li>`).join('')}</ul></div>` : '';
  const link = data.comment_url ? `<p class="foot">Comment posted: <a href="${escapeHtml(data.comment_url)}" target="_blank" rel="noopener">view on GitHub</a></p>` : '';
  prResult.innerHTML = `<p class="headline">${headline}</p>${table}${rest}${link}`;
}

prBtn.addEventListener('click', async () => {
  if (STATIC) { prStatus.hidden = false; prStatus.textContent = `The pull-request check needs ${LIVE_ONLY}`; return; }
  const number = parseInt(document.getElementById('prNumber').value, 10);
  prStatus.hidden = false;
  if (!currentRepo) { prStatus.textContent = 'Run an analysis first. The check reuses it.'; return; }
  if (!number || number < 1) { prStatus.textContent = 'Enter a pull request number.'; return; }
  prBtn.disabled = true;
  prBtnLabel.textContent = 'Checking…';
  prStatus.innerHTML = `<span class="spinner" aria-hidden="true"></span>Fetching the files changed in #${number}…`;
  prResult.innerHTML = '';
  try {
    const res = await fetch('/pr-risk', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ repo: currentRepo, pr_number: number, post_comment: document.getElementById('prPost').checked }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Pull request check failed.');
    prStatus.textContent = `#${number}: ${plural(data.files.length, 'changed file')}.`;
    renderPrReport(data);
  } catch (err) {
    prStatus.textContent = err.message;
  } finally {
    prBtn.disabled = false;
    prBtnLabel.textContent = 'Check pull request';
  }
});

const roBtn = document.getElementById('rollingOriginBtn');
const roBtnLabel = roBtn.querySelector('.run-btn-label');
const roProgress = document.getElementById('rollingOriginProgress');
const roStatus = document.getElementById('rollingOriginStatus');
const roResults = document.getElementById('rollingOriginResults');

roBtn.addEventListener('click', () => {
  if (STATIC) { roResults.innerHTML = `<p class="muted">Rolling-origin evaluation needs ${LIVE_ONLY}</p>`; return; }
  if (!currentRepo) return;
  const horizon_days = parseInt(document.getElementById('horizon').value, 10);

  roBtn.disabled = true;
  roBtnLabel.textContent = 'Running…';
  roResults.innerHTML = '';
  roStatus.textContent = 'Starting…';
  roProgress.hidden = false;

  const params = new URLSearchParams({ repo: currentRepo, horizon_days });
  [0.5, 0.65, 0.8].forEach(c => params.append('cutoffs', c));
  const es = new EventSource(`/rolling-origin/stream?${params.toString()}`);

  es.addEventListener('progress', (ev) => {
    roStatus.textContent = JSON.parse(ev.data).message;
  });

  es.addEventListener('result', (ev) => {
    roProgress.hidden = true;
    roBtn.disabled = false;
    roBtnLabel.textContent = 'Run rolling-origin evaluation';
    renderRollingOrigin(JSON.parse(ev.data));
    es.close();
  });

  es.addEventListener('error', (ev) => {
    roProgress.hidden = true;
    roBtn.disabled = false;
    roBtnLabel.textContent = 'Run rolling-origin evaluation';
    let message = 'Rolling-origin evaluation failed: the connection to the server was lost. Check that the EvoMind server is running, then try again.';
    if (ev.data) {
      try { message = JSON.parse(ev.data).detail || message; } catch (_) {}
    }
    roResults.innerHTML = `<p class="error-text">${escapeHtml(message)}</p>`;
    es.close();
  });
});

function renderRollingOrigin(data) {
  const summary = Object.entries(data.summary).map(([model, s]) => `<tr>
      <td>${escapeHtml(MODEL_LABEL[model] || model)}</td>
      <td class="n">${s.f1_mean.toFixed(3)} ± ${s.f1_std.toFixed(3)}</td>
      <td class="n">${s.roc_auc_mean.toFixed(3)} ± ${s.roc_auc_std.toFixed(3)}</td>
    </tr>`).join('');
  const folds = data.folds.map(f => f.evaluation.map((r, j) => `<tr>
      <td>${j === 0 ? `${fmtDate(f.train_cutoff)} → ${fmtDate(f.test_cutoff)}<span class="hint" style="display:block">${f.train_files} train, ${f.test_files} test files</span>` : ''}</td>
      <td>${escapeHtml(MODEL_LABEL[r.model_name] || r.model_name)}</td>
      <td class="n">${r.f1.toFixed(3)}</td>
      <td class="n">${r.roc_auc.toFixed(3)}</td>
    </tr>`).join('')).join('');
  roResults.innerHTML = `
    <div class="table-wrap"><table><thead><tr><th>Model</th><th class="n">F1, mean ± sd</th><th class="n">ROC-AUC, mean ± sd</th></tr></thead><tbody>${summary}</tbody></table></div>
    <div class="table-wrap" style="margin-top:24px"><table><thead><tr><th>Train → test cutoff</th><th>Model</th><th class="n">F1</th><th class="n">ROC-AUC</th></tr></thead><tbody>${folds}</tbody></table></div>`;
}

fetch('/static/sample-analysis.json', { method: 'HEAD' })
  .then(r => { if (r.ok) document.getElementById('sampleLink').hidden = false; })
  .catch(() => {});

if (new URLSearchParams(location.search).has('sample')) {
  fetch('/static/sample-analysis.json')
    .then(r => r.json())
    .then(data => {
      currentRepo = data.repo;
      document.getElementById('repo').value = data.repo;
      render(data);
      document.getElementById('stamp').textContent = 'Saved analysis';
    })
    .catch(() => showError('The saved analysis could not be loaded.'));
}
