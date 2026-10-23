import { reduce, clamp, smooth, flags } from './shared.js?v=1';
import { startCritters } from './critters.js?v=2';
const app = document.getElementById('app');
const canvas = document.getElementById('city');
const hero = document.getElementById('hero');
const scanLog = document.getElementById('scanLog');
const scanHeadline = document.getElementById('scanHeadline');
const scanSteps = document.getElementById('scanSteps');
const scanTime = document.getElementById('scanTime');
const focusCard = document.getElementById('focusCard');
const introError = document.getElementById('introError');
const toTop = document.getElementById('toTop');
const motionToggle = document.getElementById('motionToggle');
const SWEEP_MS = 20000, ZOOM_MS = 2600, GROW_MS = 1600;

let state = 'idle';
let lenis = null;
let scanStart = 0, zoomStart = 0, timer = null;
let onZoom = () => {}, onReset = () => {}, buildCity = null, cityData = null;
let doneAt = 0;
motionToggle.addEventListener('click', () => {
  flags.paused = !flags.paused;
  motionToggle.setAttribute('aria-pressed', String(flags.paused));
  document.getElementById('motionLabel').textContent = flags.paused ? 'Play background' : 'Pause background';
});

function bandName(score) {
  return score >= 0.66 ? 'Critical' : score >= 0.5 ? 'Serious' : score >= 0.33 ? 'Watch' : 'Low';
}
function addDoneStep(text) {
  const li = document.createElement('li');
  li.innerHTML = '<span></span><span>✓</span>';
  li.firstChild.textContent = text.replace(/…$/, '');
  scanSteps.appendChild(li);
  while (scanSteps.children.length > 5) scanSteps.firstElementChild.remove();
}
function showResults(animated) {
  state = 'done';
  hero.classList.add('out');
  canvas.classList.add('blurred');
  scanLog.classList.add('out');
  focusCard.classList.add('out');
  document.body.classList.remove('locked');
  doneAt = performance.now();
  startCritters();
  setTimeout(() => { hero.hidden = true; }, animated ? 700 : 0);
  if (animated && !reduce) {
    app.classList.add('rise');
    setTimeout(() => app.classList.remove('rise'), 1200);
  }
  if (lenis) lenis.resize();
}

if (location.search.includes('sample')) showResults(false);

document.querySelectorAll('[data-example]').forEach(b => b.addEventListener('click', () => {
  const input = document.getElementById('introRepo');
  input.value = b.dataset.example;
  input.focus();
}));

document.getElementById('introForm').addEventListener('submit', (e) => {
  e.preventDefault();
  const input = document.getElementById('introRepo');
  const value = input.value.trim();
  if (!value) { input.focus(); return; }
  document.getElementById('repo').value = value;
  state = 'scanning';
  scanStart = performance.now();
  introError.hidden = true;
  hero.classList.add('out');
  document.getElementById('scanRepo').textContent = 'Scanning ' + value.replace(/^https?:\/\/(www\.)?github\.com\//, '').replace(/\.git$/, '');
  scanHeadline.textContent = 'Starting the scan…';
  scanSteps.innerHTML = '';
  scanTime.textContent = '0s';
  scanLog.hidden = false;
  scanLog.classList.remove('out');
  clearInterval(timer);
  timer = setInterval(() => {
    const s = Math.floor((performance.now() - scanStart) / 1000);
    scanTime.textContent = s < 60 ? `${s}s` : `${Math.floor(s / 60)}m ${s % 60}s`;
  }, 1000);
  document.getElementById('analyzeForm').requestSubmit();
});

document.addEventListener('evo:progress', (e) => {
  if (state !== 'scanning') return;
  if (scanHeadline.textContent !== 'Starting the scan…') addDoneStep(scanHeadline.textContent);
  scanHeadline.textContent = e.detail;
});

document.addEventListener('evo:error', (e) => {
  if (state !== 'scanning') return;
  clearInterval(timer);
  state = 'idle';
  onReset();
  scanLog.hidden = true;
  hero.classList.remove('out');
  introError.textContent = e.detail;
  introError.hidden = false;
});

document.addEventListener('evo:data', (e) => {
  if (!e.detail.city || !e.detail.city.length) return;
  cityData = e.detail.city;
  if (buildCity) buildCity(cityData);
});

document.addEventListener('evo:result', (e) => {
  if (state !== 'scanning') return;
  clearInterval(timer);
  const files = e.detail.top_risk_files || [];
  const top = files[0];
  if (top) {
    document.getElementById('focusPath').textContent = String(top.file_path).replace(/\\/g, '/');
    const r = top.reasons && top.reasons[0];
    const why = r ? ` · ${r.label} in the top ${Math.max(1, Math.round((1 - r.percentile) * 100))}%` : '';
    document.getElementById('focusMeta').textContent = `Risk ${top.risk_score.toFixed(2)} · ${bandName(top.risk_score)}${why}`;
  }
  scanLog.classList.add('out');
  focusCard.classList.add('in');
  state = 'zooming';
  zoomStart = performance.now() + (buildCity && cityData ? GROW_MS : 0);
  onZoom(files.filter(f => f.risk_score >= 0.5).length);
  setTimeout(() => showResults(true), reduce ? 0 : ZOOM_MS + 1000 + (buildCity && cityData ? GROW_MS : 0));
});

addEventListener('scroll', () => {
  toTop.classList.toggle('show', !document.body.classList.contains('locked') && scrollY > 600);
}, { passive: true });
toTop.addEventListener('click', () => {
  if (lenis) lenis.scrollTo(0, { duration: 0.9, easing: (x) => 1 - Math.pow(1 - x, 4) });
  else scrollTo({ top: 0, behavior: reduce ? 'auto' : 'smooth' });
});

const [LenisMod, THREE] = reduce ? [null, null] : (await Promise.allSettled([
  import('/static/vendor/lenis.mjs'),
  import('/static/vendor/three.module.js'),
])).map(r => r.status === 'fulfilled' ? r.value : null);
if (LenisMod) {
  lenis = new LenisMod.default({ lerp: 0.09, smoothWheel: true, wheelMultiplier: 0.9 });
  const lenisRaf = (t) => { lenis.raf(t); requestAnimationFrame(lenisRaf); };
  requestAnimationFrame(lenisRaf);
}

if (!THREE) {
  canvas.hidden = true;
  motionToggle.hidden = true;
} else {
  const small = innerWidth < 700;
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
  renderer.setPixelRatio(Math.min(devicePixelRatio, 1.5));
  const scene = new THREE.Scene();
  scene.fog = new THREE.Fog(0x010102, 45, 120);
  const camera = new THREE.PerspectiveCamera(40, 1, 0.1, 400);

  const gap = 2.2;
  let N = small ? 12 : 18, half = (N - 1) * gap / 2, span = 2 * half + 6;
  let seed = 1 + Math.floor(Math.random() * 2147483645);
  const rand = () => (seed = (seed * 16807) % 2147483647) / 2147483647;
  const geo = new THREE.BoxGeometry(1.5, 1, 1.5);
  geo.translate(0, 0.5, 0);
  const cityMat = new THREE.MeshStandardMaterial({ color: 0xffffff, roughness: 0.5, metalness: 0.25 });
  let city = new THREE.InstancedMesh(geo, cityMat, N * N);
  const towers = [];
  const m = new THREE.Matrix4(), q = new THREE.Quaternion(), p = new THREE.Vector3(), sc = new THREE.Vector3();
  for (let i = 0; i < N; i++) {
    for (let j = 0; j < N; j++) {
      const x = i * gap - half, z = j * gap - half;
      const centre = 1 - Math.hypot(x, z) / (half * 1.6);
      const h = 0.4 + Math.pow(rand(), 2.2) * 11 * clamp(centre, 0.15, 1);
      m.compose(p.set(x, 0, z), q, sc.set(1, h, 1));
      city.setMatrixAt(towers.length, m);
      towers.push({ x, z, h, risky: h > 3.5 && rand() < 0.22, seen: false });
    }
  }
  let grid = towers.slice(), realCity = false, topTower = null, growStart = 0;
  const base = new THREE.Color(0x3a3e4a), scanned = new THREE.Color(0x30356a), red = new THREE.Color(0xeb5757), tmp = new THREE.Color();
  scene.add(city);

  let gridHelper = new THREE.GridHelper(N * gap + 10, N + 5, 0x23252a, 0x16171b);
  scene.add(gridHelper);
  scene.add(new THREE.AmbientLight(0xffffff, 0.6));
  const sun = new THREE.DirectionalLight(0xc9cdff, 1.4);
  sun.position.set(25, 45, 15);
  scene.add(sun);
  const glow = new THREE.PointLight(0xeb5757, 0, 40);
  scene.add(glow);

  const beam = new THREE.Group();
  const sheet = new THREE.Mesh(new THREE.PlaneGeometry(N * gap + 6, 16),
    new THREE.MeshBasicMaterial({ color: 0xeb5757, transparent: true, opacity: 0.14, side: THREE.DoubleSide, blending: THREE.AdditiveBlending, depthWrite: false }));
  sheet.rotation.y = Math.PI / 2;
  sheet.position.y = 8;
  beam.add(sheet, new THREE.Mesh(new THREE.BoxGeometry(0.12, 0.12, N * gap + 6), new THREE.MeshBasicMaterial({ color: 0xff6b6b })));
  beam.visible = false;
  scene.add(beam);

  const mastH = 15;
  const mast = new THREE.Mesh(new THREE.CylinderGeometry(0.18, 0.32, mastH, 12), new THREE.MeshStandardMaterial({ color: 0x2a2d36, roughness: 0.6 }));
  mast.position.y = mastH / 2;
  const lamp = new THREE.Mesh(new THREE.SphereGeometry(0.55, 20, 16), new THREE.MeshBasicMaterial({ color: 0xff4040 }));
  lamp.position.y = mastH;
  scene.add(mast, lamp);
  const siren = new THREE.Group();
  siren.position.y = mastH;
  const tilt = 0.32;
  const coneGeo = new THREE.ConeGeometry(7, 46, 40, 1, true);
  coneGeo.translate(0, -23, 0);
  coneGeo.rotateZ(Math.PI / 2 - tilt);
  const coneMat = new THREE.MeshBasicMaterial({ color: 0xff3030, transparent: true, opacity: 0, side: THREE.DoubleSide, blending: THREE.AdditiveBlending, depthWrite: false });
  const spots = [];
  [0, Math.PI].forEach(a => {
    const arm = new THREE.Group();
    arm.rotation.y = a;
    arm.add(new THREE.Mesh(coneGeo, coneMat));
    const spot = new THREE.SpotLight(0xff3030, 0, 0, tilt, 0.6, 0);
    spot.target.position.set(Math.cos(tilt) * 30, -Math.sin(tilt) * 30, 0);
    arm.add(spot, spot.target);
    spots.push(spot);
    siren.add(arm);
  });
  scene.add(siren);

  const signCanvas = document.createElement('canvas');
  signCanvas.width = signCanvas.height = 128;
  const g = signCanvas.getContext('2d');
  g.beginPath(); g.moveTo(64, 12); g.lineTo(120, 112); g.lineTo(8, 112); g.closePath();
  g.fillStyle = '#f2c94c'; g.fill();
  g.lineJoin = 'round'; g.lineWidth = 8; g.strokeStyle = '#1a1a1a'; g.stroke();
  g.fillStyle = '#1a1a1a'; g.font = 'bold 64px Inter, Arial, sans-serif'; g.textAlign = 'center'; g.fillText('!', 64, 100);
  const signTex = new THREE.CanvasTexture(signCanvas);
  signTex.colorSpace = THREE.SRGBColorSpace;
  const signMat = new THREE.SpriteMaterial({ map: signTex, transparent: true, fog: false });
  const signs = [];
  const addSign = (tw) => {
    const sg = { tw, k: towers.indexOf(tw), sprite: new THREE.Sprite(signMat), shownAt: -1 };
    sg.sprite.visible = false;
    scene.add(sg.sprite);
    signs.push(sg);
  };
  towers.filter(tw => tw.risky).forEach(addSign);

  const towerAt = (x, z) => {
    const i = Math.round((x + half) / gap), j = Math.round((z + half) / gap);
    return i < 0 || j < 0 || i >= N || j >= N ? null : grid[i * N + j];
  };
  const hits = (x, y, z, skipTw, pad) => {
    if (Math.hypot(x, z) < 0.6 + pad && y < mastH + 1) return true;
    const tw = towerAt(x, z);
    return !!tw && tw !== skipTw && Math.abs(x - tw.x) < 0.75 + pad && Math.abs(z - tw.z) < 0.75 + pad && y < tw.h + pad;
  };
  const sightClear = (cam, tw) => {
    for (const aimY of [tw.h * 0.6, tw.h + 0.5]) {
      for (let n = 0; n < 32; n++) {
        const f = n / 32;
        if (hits(cam.x + (tw.x - cam.x) * f, cam.y + (aimY - cam.y) * f, cam.z + (tw.z - cam.z) * f, tw, 0.3)) return false;
      }
    }
    return true;
  };
  const pathClear = (from, cam, tw) => {
    for (let n = 0; n <= 24; n++) {
      const f = 0.4 + 0.6 * n / 24;
      if (hits(from.x + (cam.x - from.x) * f, from.y + (cam.y - from.y) * f, from.z + (cam.z - from.z) * f, tw, 0.8)) return false;
    }
    return true;
  };

  let orbitA = 0.75;
  let pick = null;
  let R = small ? 44 : 50, orbitY = small ? 34 : 30;
  const pickTarget = (pool) => {
    const from = { x: Math.cos(orbitA) * R, y: orbitY, z: Math.sin(orbitA) * R };
    const choices = [];
    pool.forEach(tw => {
      const baseAng = Math.atan2(from.z - tw.z, from.x - tw.x);
      for (const k of [0, 1, -1, 2, -2, 3, -3]) {
        const ang = baseAng + k * 0.25;
        const cam = { x: tw.x + Math.cos(ang) * 10, y: tw.h + 3.5, z: tw.z + Math.sin(ang) * 10 };
        if (sightClear(cam, tw) && pathClear(from, cam, tw)) { choices.push({ tw, ang, cost: Math.abs(k) }); break; }
      }
    });
    if (!choices.length) {
      const tw = [...pool].sort((a, b) => b.h - a.h)[0] || towers[0];
      return { tw, ang: Math.atan2(from.z - tw.z, from.x - tw.x), lift: 6 };
    }
    const easy = choices.filter(c => c.cost <= 1);
    const list = easy.length ? easy : choices;
    return { ...list[Math.floor(Math.random() * list.length)], lift: 0 };
  };

  onZoom = (highRisk) => {
    towers.forEach(tw => { tw.seen = true; });
    if (realCity && topTower) {
      pick = pickTarget([topTower]);
      return;
    }
    const reds = towers.filter(tw => tw.risky);
    pick = pickTarget(reds.length ? reds : [...towers].sort((a, b) => b.h - a.h).slice(0, 25));
    if (!pick.tw.risky) { pick.tw.risky = true; addSign(pick.tw); }
    reds.filter(tw => tw !== pick.tw).sort(() => Math.random() - 0.5).slice(Math.max(0, highRisk - 1)).forEach(tw => { tw.risky = false; });
  };
  onReset = () => {
    towers.forEach(tw => { tw.seen = false; });
    pick = null;
  };
  buildCity = (files) => {
    const list = [...files].sort((a, b) => a.file_path.localeCompare(b.file_path));
    N = Math.max(4, Math.ceil(Math.sqrt(list.length)));
    half = (N - 1) * gap / 2;
    span = 2 * half + 6;
    R = Math.max(30, half * 2.2 + 22);
    orbitY = R * 0.62;
    scene.remove(city);
    city.dispose();
    city = new THREE.InstancedMesh(geo, cityMat, list.length);
    towers.length = 0;
    grid = new Array(N * N).fill(null);
    list.forEach((f, idx) => {
      const i = Math.floor(idx / N), j = idx % N;
      const tw = { x: i * gap - half, z: j * gap - half, h: 0.6 + Math.log10(f.loc + 1) * 3.2, risky: f.risk_score >= 0.5, seen: true, file: f };
      towers.push(tw);
      grid[i * N + j] = tw;
      m.compose(p.set(tw.x, 0, tw.z), q, sc.set(1, 0.01, 1));
      city.setMatrixAt(idx, m);
      city.setColorAt(idx, base);
    });
    scene.add(city);
    scene.remove(gridHelper);
    gridHelper = new THREE.GridHelper(N * gap + 10, N + 5, 0x23252a, 0x16171b);
    scene.add(gridHelper);
    signs.forEach(sg => scene.remove(sg.sprite));
    signs.length = 0;
    towers.filter(tw => tw.risky).forEach(addSign);
    topTower = towers.reduce((a, b) => (b.file.risk_score > a.file.risk_score ? b : a), towers[0]);
    realCity = true;
    pick = null;
    growStart = performance.now();
    if (state === 'done') onZoom(0);
  };
  if (cityData) buildCity(cityData);
  if (state === 'done' && !realCity) onZoom(document.querySelectorAll('#riskTableBody .pill.neg, #riskTableBody .pill.warn').length || 5);

  const centre = new THREE.Vector3(0, 2, 0), look = new THREE.Vector3(), orbit = new THREE.Vector3(), close = new THREE.Vector3(), aim = new THREE.Vector3();
  function resize() {
    const w = canvas.clientWidth, h = canvas.clientHeight;
    renderer.setSize(w, h, false);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
  }
  addEventListener('resize', resize);
  resize();

  let alarm = 0, last = performance.now(), lowRes = false;
  function frame(now) {
    requestAnimationFrame(frame);
    if (flags.paused) { last = now; return; }
    const calm = state === 'done' && now - doneAt > 5500;
    if (calm && now - last < 50) return;
    if (calm !== lowRes) { lowRes = calm; renderer.setPixelRatio(Math.min(devicePixelRatio, 1.5) * (calm ? 0.6 : 1)); resize(); }
    const dt = Math.min((now - last) / 1000, 0.1);
    last = now;
    const t = now / 1000;
    if (growStart && now - growStart < GROW_MS + 600) {
      towers.forEach((tw, k) => {
        const g = smooth(0, 1, (now - growStart - (Math.hypot(tw.x, tw.z) / (half + 1)) * 500) / (GROW_MS - 500));
        m.compose(p.set(tw.x, 0, tw.z), q, sc.set(1, Math.max(0.01, tw.h * g), 1));
        city.setMatrixAt(k, m);
      });
      city.instanceMatrix.needsUpdate = true;
    }
    if (state !== 'zooming') orbitA += dt * (state === 'done' ? 0.012 : 0.04);

    let beamX = null;
    if (state === 'scanning') {
      beamX = -half - 3 + ((now - scanStart) % SWEEP_MS) / SWEEP_MS * span;
      towers.forEach(tw => { if (tw.x <= beamX) tw.seen = true; });
    }
    beam.visible = beamX !== null;
    if (beamX !== null) beam.position.x = beamX;

    let reds = 0;
    towers.forEach((tw, k) => {
      if (!tw.seen) tmp.copy(base);
      else if (tw.risky) { reds++; tmp.copy(red).multiplyScalar(state === 'done' ? 0.9 + 0.1 * Math.sin(t * 1.5 + k) : 0.7 + 0.3 * Math.sin(t * 4 + k)); }
      else tmp.copy(scanned);
      city.setColorAt(k, tmp);
    });
    city.instanceColor.needsUpdate = true;

    const d = state === 'zooming' ? smooth(0, 1, (now - zoomStart) / ZOOM_MS) : state === 'done' && pick ? 1 - smooth(0, 1, (now - doneAt - 1200) / 4000) : 0;
    alarm += ((reds && state !== 'done' ? 1 : 0) - alarm) * 0.05;
    siren.rotation.y = t * 1.4;
    coneMat.opacity = 0.11 * alarm;
    spots.forEach(sp => { sp.intensity = 6 * alarm; });
    lamp.scale.setScalar(1 + 0.25 * alarm * Math.abs(Math.sin(t * 6)));

    signs.forEach(sg => {
      const on = sg.tw.seen && sg.tw.risky;
      if (on && sg.shownAt < 0) sg.shownAt = t;
      if (!on) sg.shownAt = -1;
      sg.sprite.visible = on;
      if (!on) return;
      const x = Math.min(1, (t - sg.shownAt) / 0.45) - 1;
      const size = 1.5 * (1 + 2.70158 * x * x * x + 1.70158 * x * x);
      sg.sprite.scale.set(size, size, 1);
      sg.sprite.position.set(sg.tw.x, sg.tw.h + 1.6 + Math.sin(t * 2.2 + sg.k) * 0.3, sg.tw.z);
      if (pick && sg.tw !== pick.tw && (d > 0.3 || camera.position.distanceTo(sg.sprite.position) < 7)) sg.sprite.visible = false;
    });

    orbit.set(Math.cos(orbitA) * R, orbitY, Math.sin(orbitA) * R);
    if (pick) {
      close.set(pick.tw.x + Math.cos(pick.ang) * 10, pick.tw.h + 3.5 + pick.lift, pick.tw.z + Math.sin(pick.ang) * 10);
      aim.set(pick.tw.x, pick.tw.h * 0.6, pick.tw.z);
      glow.position.set(pick.tw.x, pick.tw.h + 2, pick.tw.z);
    }
    camera.position.lerpVectors(orbit, close, d);
    look.lerpVectors(centre, aim, d);
    camera.lookAt(look);
    glow.intensity = pick && reds ? 30 * d + 4 : 0;
    renderer.render(scene, camera);
  }
  requestAnimationFrame(frame);
}
