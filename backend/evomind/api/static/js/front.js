import { reduce, smooth } from './shared.js?v=1';
import { play } from './sound.js?v=2';
import { startFigure } from './figure.js?v=2';

const front = document.getElementById('hero');
const figCanvas = document.getElementById('fig');
const rush = document.getElementById('rush');
const trail = document.getElementById('trail');
const bubble = document.getElementById('introForm');
const cloud = document.getElementById('cloud');
const input = document.getElementById('introRepo');
const line = input.closest('.line');
const errorEl = document.getElementById('introError');
const stamp = document.getElementById('analyzeStamp');
const NS = 'http://www.w3.org/2000/svg';
const narrow = matchMedia('(max-width: 760px), (max-aspect-ratio: 1/1)');
const cssVar = (n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const isDark = () => document.documentElement.getAttribute('data-theme') === 'dark';
const colors = () => ({ ink: cssVar('--f-ink'), body: cssVar('--f-body'), red: cssVar('--f-red'), paper: cssVar('--f-paper') });
let fig = null;

const place = (w, h) => (narrow.matches ? { x: 0.12, y: h > w * 1.3 ? 0.22 : 0.05, s: Math.min(0.95, w / 560) } : { x: 0.46, y: 0, s: 1 });

const roughPath = (pts) => pts.map((p, i) => `${i ? 'L' : 'M'}${p[0].toFixed(1)} ${p[1].toFixed(1)}`).join(' ') + ' Z';
function cloudPoints(w, h, seed) {
  let s = seed;
  const r = () => (s = (s * 16807) % 2147483647) / 2147483647;
  const cx = w / 2, cy = h / 2, rx = w / 2 - 14, ry = h / 2 - 12;
  const bumps = Math.max(8, Math.round((w + h) / 70)), pts = [];
  for (let b = 0; b < bumps; b++) {
    const a0 = b / bumps * Math.PI * 2, a1 = (b + 1) / bumps * Math.PI * 2;
    for (let k = 0; k <= 10; k++) {
      const a = a0 + (a1 - a0) * k / 10;
      const bulge = Math.sin(k / 10 * Math.PI) * (16 + r() * 0.6);
      const ex = Math.cos(a), ey = Math.sin(a);
      const sx = Math.pow(Math.abs(ex), 0.35) * Math.sign(ex), sy = Math.pow(Math.abs(ey), 0.35) * Math.sign(ey);
      pts.push([cx + sx * rx + ex * bulge + (r() - 0.5) * 1.6, cy + sy * ry + ey * bulge + (r() - 0.5) * 1.6]);
    }
  }
  return pts;
}
function drawCloud() {
  const { width: w, height: h } = cloud.getBoundingClientRect();
  if (!w || !h) return;
  cloud.setAttribute('viewBox', `0 0 ${w} ${h}`);
  cloud.innerHTML = '';
  const add = (d, attrs) => {
    const p = document.createElementNS(NS, 'path');
    p.setAttribute('d', d);
    Object.entries(attrs).forEach(([k, v]) => p.setAttribute(k, v));
    cloud.appendChild(p);
  };
  const ink = cssVar('--f-ink');
  add(roughPath(cloudPoints(w, h, 5)), { fill: cssVar('--f-bubble') });
  add(roughPath(cloudPoints(w, h, 5)), { fill: 'none', stroke: ink, 'stroke-width': 2, 'stroke-linejoin': 'round', opacity: 0.9 });
  add(roughPath(cloudPoints(w, h, 9)), { fill: 'none', stroke: ink, 'stroke-width': 1.2, 'stroke-linejoin': 'round', opacity: 0.7 });
}
drawCloud();
new ResizeObserver(drawCloud).observe(bubble);

document.querySelectorAll('[data-example]').forEach((b, i) => {
  const svg = document.createElementNS(NS, 'svg');
  svg.setAttribute('viewBox', '0 0 100 40');
  svg.setAttribute('preserveAspectRatio', 'none');
  svg.setAttribute('aria-hidden', 'true');
  const p = document.createElementNS(NS, 'path');
  const j = (k) => (Math.sin(i * 7.3 + k * 3.1) + 1) * 2;
  p.setAttribute('d', `M8 ${22 + j(1)} C 6 ${6 + j(2)}, 52 ${2 + j(3)}, 90 ${10 + j(4)} S 96 ${34 + j(5)}, 50 ${37 - j(6)} S 2 ${30 + j(7)}, 14 ${12 + j(8)}`);
  svg.appendChild(p);
  b.appendChild(svg);
});

const dots = [0, 1, 2].map(() => {
  const c = document.createElementNS(NS, 'ellipse');
  c.setAttribute('stroke-width', '1.6');
  trail.appendChild(c);
  return c;
});
const paintDots = () => dots.forEach(c => { c.setAttribute('fill', cssVar('--f-bubble')); c.setAttribute('stroke', cssVar('--f-ink')); });
paintDots();
new MutationObserver(() => { drawCloud(); paintDots(); if (fig) fig.resize(); }).observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
function placeTrail() {
  if (!fig || !fig.head.r) return;
  const b = bubble.getBoundingClientRect();
  const sx = narrow.matches ? b.left + b.width * 0.72 : b.right - 30, sy = b.top + 8;
  const ex = fig.head.x - fig.head.r * (narrow.matches ? 0.2 : 0.72), ey = fig.head.y + fig.head.r * (narrow.matches ? 0.9 : 0.35);
  dots.forEach((c, i) => {
    const k = (i + 1) / 4;
    c.setAttribute('cx', sx + (ex - sx) * k);
    c.setAttribute('cy', sy + (ey - sy) * k - Math.sin(k * Math.PI) * 30);
    c.setAttribute('rx', (15 - i * 4) * 1.15);
    c.setAttribute('ry', 15 - i * 4);
  });
}
(function tick() {
  requestAnimationFrame(tick);
  if (!front.classList.contains('gone') && !front.hidden) placeTrail();
})();

bubble.addEventListener('submit', () => {
  if (!input.value.trim()) return;
  stamp.classList.remove('thump');
  void stamp.offsetWidth;
  stamp.classList.add('thump');
  play('stamp', { gain: 0.8 });
});
input.addEventListener('input', () => {
  line.classList.remove('struck');
  errorEl.hidden = true;
});

const ease = (k) => k * k * (3 - 2 * k);
function startRush(x0, y0) {
  const ctx = rush.getContext('2d');
  const dpr = Math.min(devicePixelRatio || 1, 2);
  const W = rush.clientWidth, H = rush.clientHeight;
  rush.width = W * dpr;
  rush.height = H * dpr;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  const GL = ['?', '?', '?', '!', '‽', '#', '?', '¿', '%', '?!', '{ }', '?', '404', '?', '&', '?'];
  const parts = Array.from({ length: 72 }, (_, i) => ({ ch: GL[i % GL.length], a: Math.random() * 6.283, t0: Math.random() * 1500, rot: (Math.random() - 0.5) * 1.2, spin: (Math.random() - 0.5) * 2, red: Math.random() < 0.12 }));
  const INK = cssVar('--f-ink'), RED = cssVar('--f-red');
  const t0 = performance.now();
  const step = (now) => {
    const el = now - t0;
    ctx.clearRect(0, 0, W, H);
    if (el > 2500) return;
    requestAnimationFrame(step);
    const k = ease(Math.min(1, el / 1500));
    const cx = x0 + (W / 2 - x0) * k, cy = y0 + (H / 2 - y0) * k;
    const fade = 1 - smooth(1900, 2500, el);
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    parts.forEach(p => {
      const life = (el - p.t0) / 900;
      if (life < 0 || life > 1) return;
      const z = life * life;
      const d = (0.04 + z * 1.1) * Math.hypot(W, H) * 0.6;
      ctx.save();
      ctx.globalAlpha = fade * (life > 0.8 ? (1 - life) / 0.2 : 1);
      ctx.translate(cx + Math.cos(p.a) * d, cy + Math.sin(p.a) * d);
      ctx.rotate(p.rot + p.spin * life);
      ctx.font = `${14 + z * 320}px "Permanent Marker", cursive`;
      ctx.fillStyle = p.red ? RED : INK;
      ctx.fillText(p.ch, 0, 0);
      ctx.restore();
    });
  };
  requestAnimationFrame(step);
}

export function dive(onReveal) {
  errorEl.hidden = true;
  line.classList.remove('struck');
  if (reduce || !fig) {
    front.classList.add('gone');
    if (fig) fig.stop();
    onReveal();
    return Promise.resolve();
  }
  front.style.setProperty('--hx', `${fig.head.x}px`);
  front.style.setProperty('--hy', `${fig.head.y}px`);
  front.classList.add('diving');
  play('whoosh', { gain: 0.5, rate: 0.85 });
  startRush(fig.head.x, fig.head.y);
  return new Promise(res => {
    setTimeout(onReveal, 1250);
    setTimeout(() => {
      front.classList.add('gone');
      fig.stop();
      res();
    }, 2500);
  });
}

export function restore(message) {
  front.classList.remove('diving', 'gone', 'out');
  front.hidden = false;
  if (fig) fig.start();
  if (message) {
    const cut = message.search(/[.!?]\s/);
    const head = document.createElement('span');
    head.textContent = cut > 0 ? message.slice(0, cut + 1) : message;
    errorEl.replaceChildren(head);
    if (cut > 0) {
      const rest = document.createElement('span');
      rest.className = 'err-rest';
      rest.hidden = true;
      rest.textContent = message.slice(cut + 2);
      const why = document.createElement('button');
      why.type = 'button';
      why.className = 'err-more';
      why.textContent = 'why?';
      why.setAttribute('aria-expanded', 'false');
      why.addEventListener('click', () => {
        rest.hidden = !rest.hidden;
        why.textContent = rest.hidden ? 'why?' : 'hide';
        why.setAttribute('aria-expanded', String(!rest.hidden));
      });
      errorEl.append(' ', why, rest);
    }
    errorEl.hidden = false;
    line.classList.add('struck');
  }
}

if (!location.search.includes('sample')) {
  import('/static/vendor/three.module.js')
    .then(THREE => startFigure(THREE, figCanvas, { place, still: reduce, colors, dark: isDark }))
    .then(f => {
      fig = f;
      narrow.addEventListener('change', () => f.resize());
    })
    .catch(() => {});
}
