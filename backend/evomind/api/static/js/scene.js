import { reduce, clamp, smooth, flags } from './shared.js?v=1';
import { play, loop } from './sound.js?v=2';
import { dive, restore } from './front.js?v=3';
const app = document.getElementById('app');
const canvas = document.getElementById('city');
const hero = document.getElementById('hero');
const scanLog = document.getElementById('scanLog');
const scanHeadline = document.getElementById('scanHeadline');
const scanSteps = document.getElementById('scanSteps');
const scanTime = document.getElementById('scanTime');
const focusCard = document.getElementById('focusCard');
const toTop = document.getElementById('toTop');
const motionToggle = document.getElementById('motionToggle');
const SWEEP_MS = 20000, ZOOM_MS = 2600, GROW_MS = 1600, FALL_MS = 1900;

let state = 'idle';
let lenis = null;
let scanStart = 0, zoomStart = 0, timer = null;
let onZoom = () => {}, onReset = () => {}, onAnswer = () => {}, buildCity = null, cityData = null;
let doneAt = 0, landed = Promise.resolve(), frontUp = !location.search.includes('sample'), fallAt = 0;
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
  frontUp = false;
  loop('scan', 0);
  if (animated) play('chime', { gain: 0.55 });
  hero.classList.add('out');
  canvas.classList.add('blurred');
  scanLog.classList.add('out');
  focusCard.classList.add('out');
  document.body.classList.remove('locked');
  doneAt = performance.now();
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
  input.dispatchEvent(new Event('input'));
  input.focus();
}));

const busy = () => state === 'scanning' || state === 'diving';
document.getElementById('introForm').addEventListener('submit', (e) => {
  e.preventDefault();
  const input = document.getElementById('introRepo');
  const value = input.value.trim();
  if (!value) { input.focus(); return; }
  if (busy()) return;
  document.getElementById('repo').value = value;
  document.getElementById('scanRepo').textContent = 'scanning ' + value.replace(/^https?:\/\/(www\.)?github\.com\//, '').replace(/\.git$/, '');
  scanHeadline.textContent = 'Starting the scan…';
  scanSteps.innerHTML = '';
  scanTime.textContent = '0s';
  onReset();
  state = 'diving';
  landed = dive(() => { frontUp = false; fallAt = performance.now(); }).then(() => {
    if (state !== 'diving') return;
    state = 'scanning';
    scanStart = performance.now();
    scanLog.hidden = false;
    scanLog.classList.remove('out');
    clearInterval(timer);
    timer = setInterval(() => {
      const s = Math.floor((performance.now() - scanStart) / 1000);
      scanTime.textContent = s < 60 ? `${s}s` : `${Math.floor(s / 60)}m ${s % 60}s`;
    }, 1000);
  });
  document.getElementById('analyzeForm').requestSubmit();
});

document.addEventListener('evo:progress', (e) => {
  if (!busy()) return;
  if (scanHeadline.textContent !== 'Starting the scan…') addDoneStep(scanHeadline.textContent);
  scanHeadline.textContent = e.detail;
  landed.then(() => {
    if (state !== 'scanning') return;
    play('tick', { gain: 0.5, gap: 120 });
    onAnswer();
  });
});

document.addEventListener('evo:queue', (e) => {
  if (busy()) scanHeadline.textContent = e.detail;
});

document.addEventListener('evo:error', (e) => {
  if (!busy()) return;
  landed.then(() => {
    clearInterval(timer);
    state = 'idle';
    loop('scan', 0);
    onReset();
    scanLog.hidden = true;
    frontUp = true;
    restore(e.detail);
  });
});

document.addEventListener('evo:data', (e) => {
  if (!e.detail.city || !e.detail.city.length) return;
  cityData = e.detail.city;
  if (buildCity) buildCity(cityData);
});

document.addEventListener('evo:result', (e) => {
  if (busy()) landed.then(() => onResult(e.detail));
});
function onResult(detail) {
  if (state !== 'scanning') return;
  clearInterval(timer);
  loop('scan', 0);
  play('whoosh', { gain: 0.3, rate: 1.35 });
  const files = detail.top_risk_files || [];
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
}

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
  await document.fonts.load('80px "Permanent Marker"').catch(() => {});
  const small = innerWidth < 700;
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
  renderer.setPixelRatio(Math.min(devicePixelRatio, 1.5));
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(40, 1, 0.1, 400);
  const PALETTES = {
    light: { paper: 0xeeeae2, ink: 0x16161a, pencil: 0x9a948a, red: 0xc8322b, tick: '#1f7a45', grid: [0xa9a297, 0xcfc8bb], beam: 0xff5a4a, beamA: 0.2 },
    dark: { paper: 0x151412, ink: 0xece6d9, pencil: 0x5f5a52, red: 0xff5d50, tick: '#6cc58a', grid: [0x4a463e, 0x2c2a25], beam: 0xff5d50, beamA: 0.16 },
  };
  const themeName = () => (document.documentElement.getAttribute('data-theme') === 'dark' ? 'dark' : 'light');
  let pal = PALETTES[themeName()];
  const col = { ink: new THREE.Color(), pencil: new THREE.Color(), red: new THREE.Color(), paper: new THREE.Color() };
  const css = (c) => `#${new THREE.Color(c).getHexString()}`;
  const uniforms = { uTime: { value: 0 }, uPaper: { value: col.paper }, uLight: { value: new THREE.Vector3(-0.5, 0.8, 0.35) }, uFog: { value: new THREE.Vector2(55, 135) } };

  const gap = 2.2;
  let N = small ? 12 : 18, half = (N - 1) * gap / 2, span = 2 * half + 6;
  let seed = 1 + Math.floor(Math.random() * 2147483645);
  const rand = () => (seed = (seed * 16807) % 2147483647) / 2147483647;
  const geo = new THREE.BoxGeometry(1.5, 1, 1.5);
  geo.translate(0, 0.5, 0);
  const cityMat = new THREE.ShaderMaterial({
    uniforms,
    vertexShader: `
      varying vec3 vN; varying vec3 vInk; varying float vDepth;
      void main() {
        vec4 wp = modelMatrix * instanceMatrix * vec4(position, 1.0);
        vN = normalize(mat3(modelMatrix * instanceMatrix) * normal);
        vInk = instanceColor;
        vec4 mv = viewMatrix * wp;
        vDepth = -mv.z;
        gl_Position = projectionMatrix * mv;
      }`,
    fragmentShader: `
      uniform vec3 uPaper; uniform vec3 uLight; uniform float uTime; uniform vec2 uFog;
      varying vec3 vN; varying vec3 vInk; varying float vDepth;
      float hash(vec2 p) { return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }
      float hatch(float x, float s) { float d = abs(fract(x / s) - 0.5) * s; return 1.0 - smoothstep(0.35, 1.1, d); }
      void main() {
        float l = dot(normalize(vN), normalize(uLight)) * 0.5 + 0.5;
        float boil = floor(uTime * 8.0);
        vec2 p = gl_FragCoord.xy + vec2(hash(vec2(boil, 1.0)), hash(vec2(boil, 2.0))) * 2.0;
        float ink = 0.0;
        if (l < 0.64) ink = max(ink, hatch(p.x + p.y, 8.5) * 0.55);
        if (l < 0.42) ink = max(ink, hatch(p.x - p.y, 8.5) * 0.6);
        vec3 fill = mix(uPaper * 1.03, vInk, 0.06);
        vec3 c = mix(fill, vInk, ink);
        gl_FragColor = vec4(mix(c, uPaper, smoothstep(uFog.x, uFog.y, vDepth)), 1.0);
      }`,
  });
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
      city.setColorAt(towers.length, col.pencil);
      towers.push({ x, z, h, cur: h, risky: h > 3.5 && rand() < 0.22, seen: false });
    }
  }
  let grid = towers.slice(), realCity = false, topTower = null, growStart = 0;
  scene.add(city);

  const EDGES = [[0,0,0,1,0,0],[1,0,0,1,0,1],[1,0,1,0,0,1],[0,0,1,0,0,0],[0,1,0,1,1,0],[1,1,0,1,1,1],[1,1,1,0,1,1],[0,1,1,0,1,0],[0,0,0,0,1,0],[1,0,0,1,1,0],[1,0,1,1,1,1],[0,0,1,0,1,1]];
  const lineMat = (k) => new THREE.ShaderMaterial({
    uniforms: { ...uniforms, uSeed: { value: k } },
    transparent: true,
    vertexShader: `
      uniform float uTime; uniform float uSeed; attribute vec3 color; varying vec3 vC; varying float vDepth;
      float hash(vec3 p) { return fract(sin(dot(p, vec3(12.9898, 78.233, 37.719))) * 43758.5453); }
      void main() {
        float boil = floor(uTime * 8.0) + uSeed * 17.0;
        vec3 j = vec3(hash(position + boil), hash(position.yzx + boil), hash(position.zxy + boil)) - 0.5;
        vec4 mv = viewMatrix * modelMatrix * vec4(position + j * 0.09, 1.0);
        vC = color; vDepth = -mv.z;
        gl_Position = projectionMatrix * mv;
      }`,
    fragmentShader: `
      uniform vec3 uPaper; uniform vec2 uFog; varying vec3 vC; varying float vDepth;
      void main() { gl_FragColor = vec4(mix(vC, uPaper, smoothstep(uFog.x, uFog.y, vDepth)), 0.9); }`,
  });
  const lineMats = [lineMat(1), lineMat(2)];
  let edgeGeo = null, edgeLines = [];
  function makeEdges() {
    edgeLines.forEach(l => scene.remove(l));
    if (edgeGeo) edgeGeo.dispose();
    edgeGeo = new THREE.BufferGeometry();
    edgeGeo.setAttribute('position', new THREE.BufferAttribute(new Float32Array(towers.length * 72), 3));
    edgeGeo.setAttribute('color', new THREE.BufferAttribute(new Float32Array(towers.length * 72), 3));
    edgeLines = lineMats.map(mt => new THREE.LineSegments(edgeGeo, mt));
    edgeLines.forEach(l => { l.frustumCulled = false; scene.add(l); });
  }
  makeEdges();
  const tintOf = (tw) => (!tw.seen ? col.pencil : tw.risky ? col.red : col.ink);
  function syncEdges() {
    const pos = edgeGeo.attributes.position.array, cl = edgeGeo.attributes.color.array;
    let o = 0;
    towers.forEach(tw => {
      const c = tintOf(tw);
      EDGES.forEach(e => {
        for (const k of [0, 3]) {
          pos[o] = tw.x - 0.75 + e[k] * 1.5; pos[o + 1] = e[k + 1] * tw.cur; pos[o + 2] = tw.z - 0.75 + e[k + 2] * 1.5;
          cl[o] = c.r; cl[o + 1] = c.g; cl[o + 2] = c.b;
          o += 3;
        }
      });
    });
    edgeGeo.attributes.position.needsUpdate = true;
    edgeGeo.attributes.color.needsUpdate = true;
  }

  let gridHelper = null;
  function makeGrid() {
    if (gridHelper) scene.remove(gridHelper);
    gridHelper = new THREE.GridHelper(N * gap + 10, N + 5, pal.grid[0], pal.grid[1]);
    gridHelper.position.y = -0.01;
    scene.add(gridHelper);
  }

  const beamMat = new THREE.MeshBasicMaterial({ transparent: true, side: THREE.DoubleSide, depthWrite: false });
  const beamLineMat = new THREE.MeshBasicMaterial();
  const beam = new THREE.Group();
  const sheet = new THREE.Mesh(new THREE.PlaneGeometry(1, 16), beamMat);
  sheet.rotation.y = Math.PI / 2;
  sheet.position.y = 8;
  const beamLine = new THREE.Mesh(new THREE.BoxGeometry(0.1, 0.1, 1), beamLineMat);
  beam.add(sheet, beamLine);
  beam.visible = false;
  scene.add(beam);
  const sizeBeam = () => { sheet.scale.x = N * gap + 6; beamLine.scale.z = N * gap + 6; };
  sizeBeam();

  const mastH = 15;
  const mastMat = new THREE.MeshBasicMaterial(), lampMat = new THREE.MeshBasicMaterial();
  const mast = new THREE.Mesh(new THREE.CylinderGeometry(0.14, 0.26, mastH, 12), mastMat);
  mast.position.y = mastH / 2;
  const lamp = new THREE.Mesh(new THREE.SphereGeometry(0.55, 20, 16), lampMat);
  lamp.position.y = mastH;
  scene.add(mast, lamp);
  const siren = new THREE.Group();
  siren.position.y = mastH;
  const tilt = 0.32;
  const coneGeo = new THREE.ConeGeometry(7, 46, 40, 1, true);
  coneGeo.translate(0, -23, 0);
  coneGeo.rotateZ(Math.PI / 2 - tilt);
  const coneMat = new THREE.MeshBasicMaterial({ transparent: true, opacity: 0, side: THREE.DoubleSide, depthWrite: false });
  [0, Math.PI].forEach(a => {
    const arm = new THREE.Group();
    arm.rotation.y = a;
    arm.add(new THREE.Mesh(coneGeo, coneMat));
    siren.add(arm);
  });
  scene.add(siren);

  const signCanvas = document.createElement('canvas');
  signCanvas.width = signCanvas.height = 128;
  const signTex = new THREE.CanvasTexture(signCanvas);
  signTex.colorSpace = THREE.SRGBColorSpace;
  function drawSign() {
    const g = signCanvas.getContext('2d');
    g.clearRect(0, 0, 128, 128);
    g.strokeStyle = css(pal.red); g.lineWidth = 7; g.lineJoin = 'round';
    g.beginPath(); g.moveTo(64, 10); g.lineTo(118, 112); g.lineTo(10, 110); g.closePath(); g.stroke();
    g.fillStyle = css(pal.red); g.font = '72px "Permanent Marker", cursive'; g.textAlign = 'center'; g.fillText('!', 64, 104);
    signTex.needsUpdate = true;
  }
  const signMat = new THREE.SpriteMaterial({ map: signTex, transparent: true, depthWrite: false, fog: false });
  const signs = [];
  const addSign = (tw) => {
    const sg = { tw, k: towers.indexOf(tw), sprite: new THREE.Sprite(signMat), shownAt: -1 };
    sg.sprite.visible = false;
    scene.add(sg.sprite);
    signs.push(sg);
  };
  towers.filter(tw => tw.risky).forEach(addSign);

  const SYMBOLS = [['?', 'ink'], ['!', 'ink'], ['‽', 'ink'], ['?', 'ink'], ['⚠', 'red'], ['#', 'ink'], ['?', 'ink'], ['?!', 'ink'], ['{ }', 'ink'], ['404', 'red'], ['?', 'ink'], ['!', 'red'], ['?', 'ink'], ['¿', 'ink']];
  const isQuestion = (t) => /[?‽¿]/.test(t);
  const symbols = SYMBOLS.map(([text, tone], k) => {
    const c = document.createElement('canvas');
    c.width = c.height = 256;
    const tex = new THREE.CanvasTexture(c);
    tex.colorSpace = THREE.SRGBColorSpace;
    const sp = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, transparent: true, depthWrite: false, fog: false }));
    const s = (small ? 5 : 7) + rand() * (small ? 5 : 8);
    sp.scale.set(s, s, 1);
    scene.add(sp);
    return { text, tone, c, tex, sp, mark: '', a: -2 + 4 * k / (SYMBOLS.length - 1) + (rand() - 0.5) * 0.2, r: 36 + rand() * 18, y: -2 + rand() * 12, ph: rand() * 6 };
  });
  function drawSymbol(s) {
    const g = s.c.getContext('2d');
    g.clearRect(0, 0, 256, 256);
    g.textAlign = 'center';
    g.textBaseline = 'middle';
    g.font = `${s.text.length > 2 ? 110 : 200}px "Permanent Marker", cursive`;
    g.lineWidth = 14;
    g.strokeStyle = css(pal.paper);
    if (s.mark !== 'tick') {
      g.strokeText(s.text, 128, 136);
      g.fillStyle = css(s.tone === 'red' ? pal.red : pal.ink);
      g.fillText(s.text, 128, 136);
    }
    g.lineCap = g.lineJoin = 'round';
    if (s.mark === 'cross') {
      g.strokeStyle = css(pal.red);
      g.lineWidth = 9;
      g.beginPath(); g.moveTo(40, 70); g.bezierCurveTo(100, 110, 160, 150, 220, 200); g.stroke();
      g.beginPath(); g.moveTo(215, 60); g.bezierCurveTo(160, 110, 110, 160, 45, 205); g.stroke();
    }
    if (s.mark === 'tick') {
      g.strokeStyle = pal.tick;
      g.lineWidth = 16;
      g.beginPath(); g.moveTo(60, 140); g.lineTo(110, 195); g.lineTo(205, 60); g.stroke();
    }
    s.tex.needsUpdate = true;
  }
  onAnswer = () => {
    const open = symbols.filter(s => isQuestion(s.text) && !s.mark);
    if (open.length <= 1) return;
    const s = open[Math.floor(rand() * open.length)];
    s.mark = rand() < 0.5 ? 'cross' : 'tick';
    drawSymbol(s);
  };

  function applyTheme() {
    pal = PALETTES[themeName()];
    col.ink.set(pal.ink); col.pencil.set(pal.pencil); col.red.set(pal.red); col.paper.set(pal.paper);
    beamMat.color.set(pal.beam); beamMat.opacity = pal.beamA;
    beamLineMat.color.set(pal.red);
    mastMat.color.set(pal.ink); lampMat.color.set(pal.red); coneMat.color.set(pal.red);
    makeGrid();
    drawSign();
    symbols.forEach(drawSymbol);
  }
  applyTheme();
  new MutationObserver(applyTheme).observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });

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
    symbols.forEach(s => { if (s.mark) { s.mark = ''; drawSymbol(s); } });
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
      const tw = { x: i * gap - half, z: j * gap - half, h: 0.6 + Math.log10(f.loc + 1) * 3.2, cur: 0.01, risky: f.risk_score >= 0.5, seen: true, file: f };
      towers.push(tw);
      grid[i * N + j] = tw;
      m.compose(p.set(tw.x, 0, tw.z), q, sc.set(1, 0.01, 1));
      city.setMatrixAt(idx, m);
      city.setColorAt(idx, tintOf(tw));
    });
    scene.add(city);
    makeEdges();
    makeGrid();
    sizeBeam();
    signs.forEach(sg => scene.remove(sg.sprite));
    signs.length = 0;
    towers.filter(tw => tw.risky).forEach(addSign);
    topTower = towers.reduce((a, b) => (b.file.risk_score > a.file.risk_score ? b : a), towers[0]);
    realCity = true;
    pick = null;
    growStart = performance.now();
    play('rumble', { gain: 0.55 });
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
    if (flags.paused || frontUp) { last = now; return; }
    loop('scan', state === 'scanning' ? 0.22 : 0);
    const fall = fallAt ? smooth(0, 1, (now - fallAt) / FALL_MS) : 1;
    const calm = state === 'done' && now - doneAt > 5500;
    if (calm && now - last < 50) return;
    if (calm !== lowRes) { lowRes = calm; renderer.setPixelRatio(Math.min(devicePixelRatio, 1.5) * (calm ? 0.6 : 1)); resize(); }
    const dt = Math.min((now - last) / 1000, 0.1);
    last = now;
    const t = now / 1000;
    uniforms.uTime.value = t;
    if (growStart && now - growStart < GROW_MS + 600) {
      towers.forEach((tw, k) => {
        const g = smooth(0, 1, (now - growStart - (Math.hypot(tw.x, tw.z) / (half + 1)) * 500) / (GROW_MS - 500));
        tw.cur = Math.max(0.01, tw.h * g);
        m.compose(p.set(tw.x, 0, tw.z), q, sc.set(1, tw.cur, 1));
        city.setMatrixAt(k, m);
      });
      city.instanceMatrix.needsUpdate = true;
    }
    if (state !== 'zooming') orbitA += dt * ((state === 'done' ? 0.012 : 0.04) + (1 - fall) * 1.1);

    let beamX = null;
    if (state === 'scanning') {
      beamX = -half - 3 + ((now - scanStart) % SWEEP_MS) / SWEEP_MS * span;
      towers.forEach(tw => { if (tw.x <= beamX) tw.seen = true; });
    }
    beam.visible = beamX !== null;
    if (beamX !== null) beam.position.x = beamX;

    let reds = 0;
    towers.forEach((tw, k) => {
      if (tw.seen && tw.risky) reds++;
      city.setColorAt(k, tintOf(tw));
    });
    city.instanceColor.needsUpdate = true;
    syncEdges();

    const d = state === 'zooming' ? smooth(0, 1, (now - zoomStart) / ZOOM_MS) : state === 'done' && pick ? 1 - smooth(0, 1, (now - doneAt - 1200) / 4000) : 0;
    alarm += ((reds && state !== 'done' ? 1 : 0) - alarm) * 0.05;
    siren.rotation.y = t * 1.4;
    coneMat.opacity = 0.08 * alarm;
    lamp.scale.setScalar(1 + 0.25 * alarm * Math.abs(Math.sin(t * 6)));

    signs.forEach(sg => {
      const on = sg.tw.seen && sg.tw.risky;
      if (on && sg.shownAt < 0) sg.shownAt = t;
      if (!on) sg.shownAt = -1;
      sg.sprite.visible = on;
      if (!on) return;
      const x = Math.min(1, (t - sg.shownAt) / 0.45) - 1;
      const size = 1.6 * (1 + 2.70158 * x * x * x + 1.70158 * x * x);
      sg.sprite.scale.set(size, size, 1);
      sg.sprite.position.set(sg.tw.x, sg.tw.cur + 1.7 + Math.sin(t * 2.2 + sg.k) * 0.3, sg.tw.z);
      if (pick && sg.tw !== pick.tw && (d > 0.3 || camera.position.distanceTo(sg.sprite.position) < 7)) sg.sprite.visible = false;
    });

    symbols.forEach(s => {
      const a = orbitA + Math.PI + s.a + Math.sin(t * 0.1 + s.ph) * 0.05;
      s.sp.position.set(Math.cos(a) * s.r * R / 50, s.y + Math.sin(t * 0.6 + s.ph) * 1.2, Math.sin(a) * s.r * R / 50);
      s.sp.material.rotation = Math.sin(t * 0.4 + s.ph) * 0.12;
      s.sp.visible = d < 0.5;
    });

    orbit.set(Math.cos(orbitA) * R, orbitY, Math.sin(orbitA) * R);
    if (pick) {
      close.set(pick.tw.x + Math.cos(pick.ang) * 10, pick.tw.h + 3.5 + pick.lift, pick.tw.z + Math.sin(pick.ang) * 10);
      aim.set(pick.tw.x, pick.tw.h * 0.6, pick.tw.z);
    }
    camera.position.lerpVectors(orbit, close, d);
    if (fall < 1) {
      const f = 1 - fall;
      camera.position.x *= 1 - 0.5 * f;
      camera.position.z *= 1 - 0.5 * f;
      camera.position.y += f * 75;
    }
    look.lerpVectors(centre, aim, d);
    camera.lookAt(look);
    renderer.render(scene, camera);
  }
  requestAnimationFrame(frame);
}
