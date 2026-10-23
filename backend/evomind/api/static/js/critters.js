import { reduce, clamp, flags } from './shared.js?v=1';

const appEl = document.getElementById('app');
const sheetEl = document.getElementById('sheet');
const scopeEl = document.getElementById('analyzeForm');
const critCanvas = document.createElement('canvas');
critCanvas.className = 'critters';
critCanvas.setAttribute('aria-hidden', 'true');
appEl.appendChild(critCanvas);
const cx2 = critCanvas.getContext('2d');
const critWrap = document.createElement('div');
critWrap.className = 'crit-inner';
const critInner = document.createElement('canvas');
critWrap.appendChild(critInner);
sheetEl.prepend(critWrap);
const cxIn = critInner.getContext('2d');
const TOTAL_BUGS = 12, STEPS_TOTAL = 12, SCALE = 1.15, REACH = 230;
const SPOTS = [[-28, -7], [-16, 8], [-4, -8], [6, 7], [-22, 3], [0, 2], [-34, -2]];
const crit = { mode: 'off', stepsDone: 0, bugs: [], flies: [], nextEscape: 0, nextFly: 0, tongue: null, cooldown: 0, aimAt: 0, prey: null };
const cham = { x: 0, y: 0, h: -0.4, headA: 0, hue: 112, phase: 0, eyeL: 0, eyeR: 0, eyeTL: 0, eyeTR: 0, eyeNext: 0, wander: null, wanderNext: 0, gulpAt: -9999, placed: false };
let critDpr = 1;

function critResize() {
  critDpr = Math.min(devicePixelRatio || 1, 2);
  critCanvas.width = Math.round(innerWidth * critDpr);
  critCanvas.height = Math.round(innerHeight * critDpr);
}
addEventListener('resize', critResize);
critResize();

function critView() {
  const r = sheetEl.getBoundingClientRect();
  return { r, x0: 40, x1: r.width - 40, y0: Math.max(40, -r.top + 40), y1: Math.min(r.height - 40, innerHeight - r.top - 40), topVisible: r.top > 8 && r.top < innerHeight - 260 };
}
function rand(a, b) { return a + Math.random() * (b - a); }
function angTo(ax, ay, bx, by) { return Math.atan2(by - ay, bx - ax); }
function angDiff(a, b) { return ((b - a + Math.PI * 3) % (Math.PI * 2)) - Math.PI; }
function turnTo(cur, want, rate) { return cur + clamp(angDiff(cur, want), -rate, rate); }
function mouth() {
  const nx = cham.x + Math.cos(cham.h) * 18 * SCALE, ny = cham.y + Math.sin(cham.h) * 18 * SCALE;
  const a = cham.h + cham.headA;
  return { x: nx + Math.cos(a) * 29 * SCALE, y: ny + Math.sin(a) * 29 * SCALE };
}
function spawnBugs(v) {
  crit.bugs = Array.from({ length: TOTAL_BUGS }, () => ({ x: rand(v.x0, v.x1), y: rand(v.y0, v.y1), h: rand(0, 6.28), speed: rand(28, 55), phase: rand(0, 6), turnAt: 0, state: 'roam', esc: null }));
}
function startHunt() {
  crit.mode = 'hunt';
  crit.stepsDone = 0;
  crit.bugs = [];
  crit.flies = [];
  crit.nextEscape = performance.now() + 4000;
}
export function startCritters() {
  if (crit.mode === 'off') { crit.mode = 'flies'; crit.nextFly = performance.now() + 3000; }
}
scopeEl.addEventListener('submit', () => { if (!document.body.classList.contains('locked')) startHunt(); });
document.addEventListener('evo:progress', () => { if (crit.mode === 'hunt') crit.stepsDone++; });
document.addEventListener('evo:result', () => { if (crit.mode === 'hunt') crit.mode = 'feast'; });
document.addEventListener('evo:error', () => { if (crit.mode === 'hunt') crit.mode = 'feast'; });

function bugTarget() {
  if (crit.mode === 'hunt') return Math.max(1, Math.round(TOTAL_BUGS * (1 - crit.stepsDone / STEPS_TOTAL)));
  return 0;
}
function aliveBugs() { return crit.bugs.filter(b => b.state !== 'caught'); }

function updateBug(b, dt, now, v) {
  b.phase += dt * 18;
  if (b.state === 'escape') {
    b.h = turnTo(b.h, angTo(b.x, b.y, b.esc.x, b.esc.y), 8 * dt);
    b.x += Math.cos(b.h) * 90 * dt;
    b.y += Math.sin(b.h) * 90 * dt;
    if (b.x < -4 || b.y < -4) b.state = 'out';
    return;
  }
  if (b.state === 'out') {
    b.x += Math.cos(b.h) * 40 * dt;
    b.y += Math.sin(b.h) * 40 * dt;
    return;
  }
  if (b.state !== 'roam') return;
  if (now > b.turnAt) { b.h += rand(-1.4, 1.4); b.turnAt = now + rand(400, 1400); b.speed = crit.mode === 'feast' ? rand(4, 10) : rand(18, 55); }
  b.x += Math.cos(b.h) * b.speed * dt;
  b.y += Math.sin(b.h) * b.speed * dt;
  if (b.x < v.x0 || b.x > v.x1) { b.h = Math.PI - b.h; b.x = clamp(b.x, v.x0, v.x1); }
  if (b.y < v.y0 || b.y > v.y1) { b.h = -b.h; b.y = clamp(b.y, v.y0, v.y1); }
}
function updateFly(f, dt, now, v) {
  f.age += dt;
  f.flap += dt * 70;
  if (f.state !== 'buzz') return;
  if (now > f.turnAt) {
    const out = Math.random() < 0.18;
    if (out && v.topVisible && cham.y < 260) { f.goal = { x: clamp(cham.x + rand(-120, 120), 30, v.x1), y: -22 }; }
    else if (out && cham.x < 260) { f.goal = { x: -22, y: clamp(cham.y + rand(-120, 120), v.y0, v.y1) }; }
    else f.goal = { x: rand(v.x0, v.x1), y: rand(v.y0, v.y1) };
    f.turnAt = now + rand(250, 650);
  }
  const want = angTo(f.x, f.y, f.goal.x, f.goal.y) + Math.sin(now / 90 + f.seed) * 0.9;
  f.h = turnTo(f.h, want, 10 * dt);
  f.x += Math.cos(f.h) * 95 * dt;
  f.y += Math.sin(f.h) * 95 * dt;
  f.trail.push([f.x, f.y]);
  if (f.trail.length > 14) f.trail.shift();
}

function chooseEscape(v, now) {
  const bugs = aliveBugs().filter(b => b.state === 'roam');
  if (!bugs.length) return;
  const b = bugs.sort((p, q) => Math.hypot(p.x - cham.x, p.y - cham.y) - Math.hypot(q.x - cham.x, q.y - cham.y))[0];
  if (v.topVisible && cham.y < 240) b.esc = { x: clamp(cham.x + rand(-110, 110), 30, v.x1), y: -26 };
  else if (cham.x < 240) b.esc = { x: -26, y: clamp(cham.y + rand(-110, 110), v.y0, v.y1) };
  else { cham.wander = v.topVisible ? { x: clamp(cham.x, 160, v.x1), y: Math.max(v.y0, 130) } : { x: 130, y: clamp(cham.y, v.y0, v.y1) }; crit.nextEscape = now + 2500; return; }
  b.state = 'escape';
  crit.nextEscape = now + rand(5000, 8000);
}

function pickPrey(now) {
  const outside = crit.bugs.find(b => b.state === 'out') || crit.flies.find(f => f.state === 'buzz' && (f.x < 0 || f.y < 0) && f.age > 0.4);
  if (outside) return { p: outside, urgent: true };
  if (aliveBugs().length > bugTarget()) {
    const roam = aliveBugs().filter(b => b.state === 'roam' || b.state === 'escape');
    if (roam.length) return { p: roam.sort((p, q) => Math.hypot(p.x - cham.x, p.y - cham.y) - Math.hypot(q.x - cham.x, q.y - cham.y))[0], urgent: false };
  }
  const fly = crit.flies.find(f => f.state === 'buzz' && f.age > f.patience);
  if (fly) return { p: fly, urgent: false };
  const stalk = aliveBugs().filter(b => b.state === 'roam' || b.state === 'escape');
  if (stalk.length) return { p: stalk.sort((p, q) => Math.hypot(p.x - cham.x, p.y - cham.y) - Math.hypot(q.x - cham.x, q.y - cham.y))[0], urgent: false, stalk: true };
  return null;
}

function updateChameleon(dt, now, v) {
  if (!cham.placed) { cham.x = rand(v.x0 + 80, v.x1 - 80); cham.y = rand(v.y0 + 60, Math.max(v.y0 + 61, Math.min(v.y1, v.y0 + 260))); cham.placed = true; }
  if (cham.y < v.y0 - 160) cham.y = v.y0 - 20;
  if (cham.y > v.y1 + 160) cham.y = v.y1 + 20;
  const hunting = crit.tongue || aliveBugs().length || crit.flies.some(f => f.state === 'buzz');
  cham.hue += ((hunting ? 22 : 112) - cham.hue) * Math.min(1, dt * 0.9);

  const t = crit.tongue;
  let look = null;
  if (t) look = t.prey;
  else {
    const choice = pickPrey(now);
    if (choice) {
      look = choice.p;
      const m = mouth();
      const d = Math.hypot(look.x - m.x, look.y - m.y);
      const reach = crit.mode === 'feast' ? 560 : REACH;
      if (choice.stalk) {
        if (d > 170) cham.wander = { x: clamp(look.x, v.x0, v.x1), y: clamp(look.y, v.y0, v.y1) };
      } else if (d < reach && now > crit.cooldown) {
        if (crit.prey !== look) { crit.prey = look; crit.aimAt = now + (choice.urgent || crit.mode === 'feast' ? 90 : 380); }
        if (now > crit.aimAt) crit.tongue = { prey: look, t0: now, len: 0, caught: false, eat: !crit.bugs.includes(look) || aliveBugs().length > bugTarget() };
      } else if (d >= reach) {
        cham.wander = { x: clamp(look.x, v.x0, v.x1), y: clamp(look.y, v.y0, v.y1) };
      }
    }
  }

  let moving = false;
  if (look && crit.mode === 'feast') cham.h = turnTo(cham.h, angTo(cham.x, cham.y, look.x, look.y), 3 * dt);
  if (!t) {
    if (!cham.wander && now > cham.wanderNext) cham.wander = { x: rand(v.x0 + 60, v.x1 - 60), y: rand(v.y0 + 40, v.y1 - 40) };
    if (cham.wander) {
      const d = Math.hypot(cham.wander.x - cham.x, cham.wander.y - cham.y);
      const want = angTo(cham.x, cham.y, cham.wander.x, cham.wander.y);
      cham.h = turnTo(cham.h, want, 2.2 * dt);
      if (d > (look ? REACH * 0.6 : 6) && Math.abs(angDiff(cham.h, want)) < 0.6) {
        const sp = look ? 70 : 32;
        cham.x += Math.cos(cham.h) * sp * dt;
        cham.y += Math.sin(cham.h) * sp * dt;
        cham.phase += sp * dt * 0.22;
        moving = true;
      } else if (d <= 6 || (look && d <= REACH * 0.6)) { cham.wander = null; cham.wanderNext = now + rand(1500, 4500); }
    }
  }
  const headWant = look ? clamp(angDiff(cham.h, angTo(cham.x, cham.y, look.x, look.y)), -0.75, 0.75) : Math.sin(now / 2300) * 0.25;
  cham.headA += (headWant - cham.headA) * Math.min(1, dt * (look ? 7 : 2));

  if (look) {
    const a = angTo(cham.x, cham.y, look.x, look.y);
    cham.eyeTL = a;
    cham.eyeTR = a;
  } else if (now > cham.eyeNext) {
    cham.eyeTL = cham.h + rand(-1.6, 1.2);
    cham.eyeTR = cham.h + rand(-1.2, 1.6);
    cham.eyeNext = now + rand(600, 1600);
  }
  cham.eyeL = turnTo(cham.eyeL, cham.eyeTL, (look ? 10 : 3) * dt);
  cham.eyeR = turnTo(cham.eyeR, look ? cham.eyeTR : cham.eyeTR, (look ? 8 : 2.4) * dt);

  if (t) {
    const m = mouth();
    const el = now - t.t0;
    const dist = Math.hypot(t.prey.x - m.x, t.prey.y - m.y);
    if (el < 120) t.len = dist * (el / 120);
    else if (el < 170) {
      t.len = dist;
      if (!t.caught) {
        t.caught = true;
        if (t.eat) t.prey.state = 'caught';
        else { t.prey.state = 'roam'; t.prey.x = Math.max(t.prey.x, 30); t.prey.y = Math.max(t.prey.y, 30); t.prey.h = angTo(t.prey.x, t.prey.y, cham.x, cham.y) + rand(-0.8, 0.8); t.prey.speed = 120; t.prey.turnAt = now + 500; }
      }
    }
    else if (el < 400) {
      const k = 1 - (el - 170) / 230;
      t.len = t.fullLen ?? (t.fullLen = dist) ;
      t.len = t.fullLen * k;
      const dir = t.dir ?? (t.dir = angTo(m.x, m.y, t.prey.x, t.prey.y));
      if (t.eat) {
        t.prey.x = m.x + Math.cos(dir) * t.len;
        t.prey.y = m.y + Math.sin(dir) * t.len;
      }
    } else {
      if (t.eat) {
        crit.bugs = crit.bugs.filter(b => b !== t.prey);
        crit.flies = crit.flies.filter(f => f !== t.prey);
        cham.gulpAt = now;
      }
      crit.tongue = null;
      crit.prey = null;
      crit.cooldown = now + (crit.mode === 'feast' ? 200 : 950);
    }
  }
  return moving;
}

function drawChameleon(ctx, now, moving) {
  const base = `hsl(${cham.hue} 46% 38%)`, dark = `hsl(${cham.hue} 50% 22%)`, light = `hsl(${cham.hue + 12} 55% 54%)`;
  ctx.save();
  ctx.translate(cham.x, cham.y);
  ctx.rotate(cham.h);
  ctx.scale(SCALE, SCALE);
  ctx.lineCap = 'round';
  ctx.lineJoin = 'round';
  const tail = [];
  for (let i = 0; i <= 44; i++) {
    const tt = i / 44;
    if (tt < 0.32) tail.push([-34 - (tt / 0.32) * 26, 0]);
    else { const u = (tt - 0.32) / 0.68; const a = -Math.PI / 2 - u * Math.PI * 2.1; const r = 14 * (1 - u * 0.78); tail.push([-60 + Math.cos(a) * r, 14 + Math.sin(a) * r]); }
  }
  for (let i = 1; i < tail.length; i++) {
    ctx.strokeStyle = i % 4 < 2 ? base : dark;
    ctx.lineWidth = 10 * (1 - i / tail.length) + 1.6;
    ctx.beginPath(); ctx.moveTo(tail[i - 1][0], tail[i - 1][1]); ctx.lineTo(tail[i][0], tail[i][1]); ctx.stroke();
  }
  const legs = [[12, -1, 1], [12, 1, -1], [-24, -1, -1], [-24, 1, 1]];
  legs.forEach(([ax, side, ph]) => {
    const sw = moving ? Math.sin(cham.phase * 6 + (ph > 0 ? 0 : Math.PI)) * 6 : 0;
    const fwd = ax > 0 ? 1 : -1;
    const ex = ax + fwd * 5 + sw * 0.6, ey = side * 15;
    const fx = ax + fwd * 9 + sw, fy = side * 21;
    ctx.strokeStyle = dark; ctx.lineWidth = 4.6;
    ctx.beginPath(); ctx.moveTo(ax, side * 9); ctx.lineTo(ex, ey); ctx.stroke();
    ctx.lineWidth = 3.2;
    ctx.beginPath(); ctx.moveTo(ex, ey); ctx.lineTo(fx, fy); ctx.stroke();
    ctx.lineWidth = 1.6;
    ctx.beginPath(); ctx.moveTo(fx, fy); ctx.lineTo(fx + 3, fy + side * 2.5); ctx.moveTo(fx, fy); ctx.lineTo(fx - 3, fy + side * 2.5); ctx.stroke();
  });
  const g = ctx.createLinearGradient(0, -15, 0, 15);
  g.addColorStop(0, dark); g.addColorStop(0.35, base); g.addColorStop(0.5, light); g.addColorStop(0.65, base); g.addColorStop(1, dark);
  ctx.fillStyle = g;
  ctx.beginPath(); ctx.ellipse(-8, 0, 31, 14.5, 0, 0, Math.PI * 2); ctx.fill();
  ctx.fillStyle = `hsl(${cham.hue + 18} 60% 60% / 0.55)`;
  SPOTS.forEach(([sx, sy]) => { ctx.beginPath(); ctx.ellipse(sx, sy, 3.2, 1.8, 0.3, 0, Math.PI * 2); ctx.fill(); });
  ctx.strokeStyle = dark; ctx.lineWidth = 1.2;
  ctx.beginPath();
  for (let x = -36; x <= 18; x += 4) { ctx.lineTo(x, 0); ctx.lineTo(x + 2, -1.6); }
  ctx.stroke();
  ctx.translate(18, 0);
  ctx.rotate(cham.headA);
  const gulp = now - cham.gulpAt < 360 ? Math.sin((now - cham.gulpAt) / 360 * Math.PI) : 0;
  if (gulp) { ctx.fillStyle = base; ctx.beginPath(); ctx.ellipse(2, 0, 7 + gulp * 3, 9 + gulp * 4, 0, 0, Math.PI * 2); ctx.fill(); }
  const hg = ctx.createLinearGradient(0, -12, 0, 12);
  hg.addColorStop(0, dark); hg.addColorStop(0.5, base); hg.addColorStop(1, dark);
  ctx.fillStyle = hg;
  ctx.beginPath(); ctx.moveTo(0, -12); ctx.quadraticCurveTo(16, -13 - gulp, 29, -2); ctx.lineTo(29, 2); ctx.quadraticCurveTo(16, 13 + gulp, 0, 12); ctx.closePath(); ctx.fill();
  ctx.strokeStyle = dark; ctx.lineWidth = 1.4;
  ctx.beginPath(); ctx.moveTo(2, 0); ctx.lineTo(24, 0); ctx.stroke();
  [[-9, cham.eyeL], [9, cham.eyeR]].forEach(([ey, ang]) => {
    ctx.fillStyle = base; ctx.beginPath(); ctx.arc(12, ey, 6.2, 0, Math.PI * 2); ctx.fill();
    ctx.strokeStyle = dark; ctx.lineWidth = 0.9;
    ctx.beginPath(); ctx.arc(12, ey, 4.4, 0, Math.PI * 2); ctx.stroke();
    ctx.beginPath(); ctx.arc(12, ey, 2.8, 0, Math.PI * 2); ctx.stroke();
    const la = ang - cham.h - cham.headA;
    const px = 12 + Math.cos(la) * 2.8, py = ey + Math.sin(la) * 2.8;
    ctx.fillStyle = '#0c0c0c'; ctx.beginPath(); ctx.arc(px, py, 1.7, 0, Math.PI * 2); ctx.fill();
    ctx.fillStyle = 'rgba(255,255,255,.8)'; ctx.beginPath(); ctx.arc(px - 0.6, py - 0.6, 0.55, 0, Math.PI * 2); ctx.fill();
  });
  ctx.restore();
}
function drawBug(ctx, b) {
  ctx.save();
  ctx.translate(b.x, b.y);
  ctx.rotate(b.h);
  ctx.scale(1.35, 1.35);
  ctx.strokeStyle = '#1c130d'; ctx.lineWidth = 1; ctx.lineCap = 'round';
  [-3, 0, 3].forEach((lx, i) => {
    const w = Math.sin(b.phase + i * 2) * 1.6;
    ctx.beginPath(); ctx.moveTo(lx, -3); ctx.lineTo(lx + w, -7.5); ctx.moveTo(lx, 3); ctx.lineTo(lx - w, 7.5); ctx.stroke();
  });
  const g = ctx.createRadialGradient(-1, -1.5, 0.5, 0, 0, 7);
  g.addColorStop(0, '#7a5b42'); g.addColorStop(1, '#1a110b');
  ctx.fillStyle = g;
  ctx.beginPath(); ctx.ellipse(-1, 0, 6.5, 4.2, 0, 0, Math.PI * 2); ctx.fill();
  ctx.fillStyle = '#120c08'; ctx.beginPath(); ctx.arc(6, 0, 2.4, 0, Math.PI * 2); ctx.fill();
  ctx.strokeStyle = '#0b0705'; ctx.lineWidth = 0.6; ctx.beginPath(); ctx.moveTo(-7, 0); ctx.lineTo(4, 0); ctx.stroke();
  ctx.restore();
}
function drawFly(ctx, f) {
  if (f.trail.length > 2) {
    for (let i = 1; i < f.trail.length; i++) {
      ctx.strokeStyle = `rgba(200, 210, 230, ${0.22 * i / f.trail.length})`;
      ctx.lineWidth = 1;
      ctx.beginPath(); ctx.moveTo(f.trail[i - 1][0], f.trail[i - 1][1]); ctx.lineTo(f.trail[i][0], f.trail[i][1]); ctx.stroke();
    }
  }
  const pop = Math.min(1, f.age / 0.2);
  ctx.save();
  ctx.translate(f.x, f.y);
  ctx.rotate(f.h);
  ctx.scale(pop, pop);
  const flap = 0.4 + Math.abs(Math.sin(f.flap)) * 0.6;
  ctx.fillStyle = 'rgba(215, 225, 245, 0.55)';
  ctx.beginPath(); ctx.ellipse(-1, -2.6, 3.6, 1.6 * flap, -0.4, 0, Math.PI * 2); ctx.fill();
  ctx.beginPath(); ctx.ellipse(-1, 2.6, 3.6, 1.6 * flap, 0.4, 0, Math.PI * 2); ctx.fill();
  ctx.fillStyle = '#1d1f22'; ctx.beginPath(); ctx.ellipse(0, 0, 3.6, 2.1, 0, 0, Math.PI * 2); ctx.fill();
  ctx.fillStyle = '#3b1f1f'; ctx.beginPath(); ctx.arc(3.3, 0, 1.5, 0, Math.PI * 2); ctx.fill();
  ctx.restore();
}
function drawTongue(ctx) {
  const t = crit.tongue;
  if (!t || t.len <= 0) return;
  const m = mouth();
  const dir = t.dir ?? angTo(m.x, m.y, t.prey.x, t.prey.y);
  const tx = m.x + Math.cos(dir) * t.len, ty = m.y + Math.sin(dir) * t.len;
  ctx.strokeStyle = '#d06d7c'; ctx.lineWidth = 2.8; ctx.lineCap = 'round';
  ctx.beginPath(); ctx.moveTo(m.x, m.y); ctx.lineTo(tx, ty); ctx.stroke();
  ctx.fillStyle = '#e88b99'; ctx.beginPath(); ctx.arc(tx, ty, 4, 0, Math.PI * 2); ctx.fill();
}

function critAllowed() {
  return crit.mode !== 'off' && !reduce && !flags.paused && innerWidth >= 860 && !document.body.classList.contains('locked');
}
let critLast = performance.now(), critWasOn = false;
function critTick(now) {
  requestAnimationFrame(critTick);
  const dt = Math.min((now - critLast) / 1000, 0.05);
  critLast = now;
  const on = critAllowed();
  if (!on) { if (critWasOn) { cx2.setTransform(1, 0, 0, 1, 0, 0); cx2.clearRect(0, 0, critCanvas.width, critCanvas.height); cxIn.setTransform(1, 0, 0, 1, 0, 0); cxIn.clearRect(0, 0, critInner.width, critInner.height); critWasOn = false; } return; }
  critWasOn = true;
  const v = critView();
  if (v.y1 - v.y0 < 120) { cx2.setTransform(1, 0, 0, 1, 0, 0); cx2.clearRect(0, 0, critCanvas.width, critCanvas.height); return; }

  if (crit.mode === 'hunt' && !crit.bugs.length) spawnBugs(v);
  if ((crit.mode === 'hunt' || crit.mode === 'feast') && now > crit.nextEscape && !crit.tongue) chooseEscape(v, now);
  if (crit.mode === 'feast' && !crit.bugs.length && !crit.tongue) { crit.mode = 'flies'; crit.nextFly = now + rand(5000, 10000); }
  if (crit.mode === 'flies' && now > crit.nextFly && crit.flies.length < 2) {
    crit.flies.push({ x: rand(v.x0, v.x1), y: rand(v.y0, v.y1), h: rand(0, 6.28), age: 0, flap: 0, turnAt: 0, goal: null, trail: [], state: 'buzz', seed: rand(0, 50), patience: rand(1.2, 3) });
    crit.nextFly = now + rand(5000, 10000);
  }
  crit.bugs.forEach(b => updateBug(b, dt, now, v));
  crit.flies.forEach(f => updateFly(f, dt, now, v));
  const moving = updateChameleon(dt, now, v);

  cx2.setTransform(1, 0, 0, 1, 0, 0);
  cx2.clearRect(0, 0, critCanvas.width, critCanvas.height);
  cx2.setTransform(critDpr, 0, 0, critDpr, v.r.left * critDpr, v.r.top * critDpr);
  drawScene(cx2, now, moving);
  const off = Math.max(0, -v.r.top), w = Math.round(v.r.width), h = Math.round(Math.min(innerHeight, v.r.height - off));
  if (critInner.width !== Math.round(w * critDpr) || critInner.height !== Math.round(h * critDpr)) {
    critInner.width = Math.round(w * critDpr);
    critInner.height = Math.round(h * critDpr);
    critInner.style.width = `${w}px`;
    critInner.style.height = `${h}px`;
  }
  critInner.style.top = `${off}px`;
  cxIn.setTransform(1, 0, 0, 1, 0, 0);
  cxIn.clearRect(0, 0, critInner.width, critInner.height);
  cxIn.setTransform(critDpr, 0, 0, critDpr, 0, -off * critDpr);
  drawScene(cxIn, now, moving);
}
function drawScene(ctx, now, moving) {
  crit.bugs.forEach(b => { if (b.state !== 'caught') drawBug(ctx, b); });
  drawChameleon(ctx, now, moving);
  drawTongue(ctx);
  crit.bugs.forEach(b => { if (b.state === 'caught') drawBug(ctx, b); });
  crit.flies.forEach(f => drawFly(ctx, f));
}
requestAnimationFrame(critTick);
