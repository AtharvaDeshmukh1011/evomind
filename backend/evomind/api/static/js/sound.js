const NAMES = ['click', 'tick', 'scan', 'rumble', 'chime', 'whoosh', 'stamp'];
const KEY = 'evomind-sound';
const buffers = {}, last = {}, loops = {}, buttons = [];
let ctx = null, master = null, muted = false;
try { muted = localStorage.getItem(KEY) === 'off'; } catch {}

function load(name) {
  fetch(`/static/media/${name}.mp3`)
    .then(r => (r.ok ? r.arrayBuffer() : Promise.reject(new Error(name))))
    .then(b => ctx.decodeAudioData(b))
    .then(buf => { buffers[name] = buf; if (loops[name]) startLoop(name); })
    .catch(() => {});
}

function unlock() {
  if (ctx) { if (ctx.state === 'suspended' && !document.hidden) ctx.resume(); return; }
  const AC = window.AudioContext || window.webkitAudioContext;
  if (!AC) return;
  ctx = new AC();
  master = ctx.createGain();
  master.gain.value = muted ? 0 : 1;
  master.connect(ctx.destination);
  NAMES.forEach(load);
}
['pointerdown', 'keydown', 'touchstart'].forEach(t => addEventListener(t, unlock, { capture: true, passive: true }));
document.addEventListener('visibilitychange', () => {
  if (!ctx) return;
  if (document.hidden) ctx.suspend(); else ctx.resume();
});

export function play(name, { gain = 1, rate = 1, gap = 0 } = {}) {
  if (!ctx || muted || !buffers[name]) return;
  const now = performance.now();
  if (gap && now - (last[name] || 0) < gap) return;
  last[name] = now;
  const src = ctx.createBufferSource();
  src.buffer = buffers[name];
  src.playbackRate.value = rate;
  const g = ctx.createGain();
  g.gain.value = gain;
  src.connect(g).connect(master);
  src.start();
}

function startLoop(name) {
  const l = loops[name];
  if (!ctx || !buffers[name] || l.src) return;
  l.g = ctx.createGain();
  l.g.gain.value = 0;
  l.g.connect(master);
  l.src = ctx.createBufferSource();
  l.src.buffer = buffers[name];
  l.src.loop = true;
  l.src.connect(l.g);
  l.src.start();
  l.g.gain.setTargetAtTime(l.want, ctx.currentTime, 0.5);
}

export function loop(name, gain, ramp = 0.4) {
  const l = loops[name] || (loops[name] = { want: -1, src: null, g: null });
  if (l.want === gain) return;
  l.want = gain;
  if (!l.src) { startLoop(name); return; }
  l.g.gain.setTargetAtTime(gain, ctx.currentTime, ramp);
}

function paint() {
  buttons.forEach(b => {
    b.setAttribute('aria-pressed', String(muted));
    b.classList.toggle('muted', muted);
    const label = b.querySelector('[data-sound-label]');
    if (label) label.textContent = muted ? 'Sound on' : 'Mute sound';
    else b.setAttribute('aria-label', muted ? 'Turn sound on' : 'Mute sound');
  });
}

function setMuted(m) {
  muted = m;
  try { localStorage.setItem(KEY, m ? 'off' : 'on'); } catch {}
  if (master) master.gain.setTargetAtTime(m ? 0 : 1, ctx.currentTime, 0.05);
  paint();
}

['soundToggle', 'soundNav'].forEach(id => {
  const b = document.getElementById(id);
  if (!b) return;
  buttons.push(b);
  b.addEventListener('click', () => {
    setMuted(!muted);
    play('click', { gain: 0.5 });
  });
});
paint();

document.addEventListener('click', (e) => {
  const el = e.target.closest('button, a[href], .nav-item');
  if (!el || el.id === 'soundToggle' || el.id === 'soundNav') return;
  play('click', { gain: 0.45, gap: 60 });
}, true);
