const RAMP = [' ', '.', ':', '-', '~', '+', '?', '!', '?', '/', '?', '{', '?', '#', '?', '%', '?', '@'];
const ERR = ['TypeError', 'undefined', 'NaN', 'null', '404', '500', 'SIGSEGV', 'panic!', 'KeyError', 'ENOENT', 'Traceback', 'segfault', 'NullPointer', 'fatal:', 'NoneType', 'IndexError', 'conflict', 'deadlock', 'timeout'];
const BIG = ['?', '?', '?', '?', '?', '¿', '?', '‽'];
const MID = ['?', '!', '#', '%', '@', '&', '?', '{', '}', '<', '>', '*', '?', '¿', '×', '?'];
const SMALL = ['?', '!', '#', '%', '@', '&', '*', '~', '$', '?', '?', '{}', '</>', '!=', '??', '?', '!', '404', 'NaN', '?!', '¿', ';', '^'];
const REDSET = new Set(['404', 'NaN']);
const S = 1.8, CHIN = -0.55;

export async function startFigure(THREE, out, { place, still = false, colors, dark }) {
  let C = colors(), isDark = dark();
  const FONT = 9, CW = FONT * 0.6, CH = FONT * 1.08;
  const ctx = out.getContext('2d');
  const renderer = new THREE.WebGLRenderer({ antialias: false, alpha: true });
  renderer.setClearColor(0x000000, 0);
  renderer.localClippingEnabled = true;
  const target = new THREE.WebGLRenderTarget(2, 2);
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(30, 1, 0.1, 300);
  scene.add(new THREE.AmbientLight(0xffffff, 0.12));
  const key = new THREE.DirectionalLight(0xffffff, 2.3);
  key.position.set(-10, 8, 12);
  const rim = new THREE.DirectionalLight(0xffffff, 0.5);
  rim.position.set(12, 2, -6);
  scene.add(key, rim);

  const ab = await (await fetch('/static/media/head.bin')).arrayBuffer();
  const dv = new DataView(ab);
  const nv = dv.getUint32(0, true), ni = dv.getUint32(4, true);
  const geo = new THREE.BufferGeometry();
  geo.setAttribute('position', new THREE.BufferAttribute(new Float32Array(ab, 8, nv * 3), 3));
  geo.setIndex(new THREE.BufferAttribute(new Uint16Array(ab, 8 + nv * 12, ni), 1));
  geo.computeVertexNormals();
  const figure = new THREE.Group();
  const clip = new THREE.Plane(new THREE.Vector3(0, -1, 0), 0);
  const bust = new THREE.Mesh(geo, new THREE.MeshStandardMaterial({ color: 0xffffff, roughness: 0.7, clippingPlanes: [clip], side: THREE.DoubleSide }));
  figure.add(bust);
  scene.add(figure);
  camera.position.set(0, 2, 34);
  camera.lookAt(0, 2, 0);

  let cols = 0, rows = 0, W = 0, H = 0, buf = null;
  function resize() {
    const dpr = Math.min(devicePixelRatio || 1, 2);
    W = out.clientWidth; H = out.clientHeight;
    if (!W || !H) return;
    out.width = W * dpr; out.height = H * dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    cols = Math.floor(W / CW); rows = Math.floor(H / CH);
    target.setSize(cols, rows);
    buf = new Uint8Array(cols * rows * 4);
    camera.aspect = W / H;
    camera.updateProjectionMatrix();
    const halfH = 34 * Math.tan(THREE.MathUtils.degToRad(15)), halfW = halfH * camera.aspect;
    const p = place(W, H);
    figure.scale.setScalar(S * p.s);
    figure.position.set(halfW * p.x, halfH * p.y, 0);
    clip.constant = figure.position.y + CHIN * S * p.s;
  }
  addEventListener('resize', () => { resize(); if (still) frame(0); });
  resize();

  let seed = 11;
  const rnd = () => (seed = (seed * 16807) % 2147483647) / 2147483647;
  const range = (a, b) => a + rnd() * (b - a);
  const hash = (x, y, k) => { let h = (x * 374761393 + y * 668265263 + k * 1274126177) | 0; h = (h ^ (h >>> 13)) * 1274126177; return ((h ^ (h >>> 16)) >>> 0) / 4294967295; };

  const glyphs = [];
  const placeGlyphs = (n, minD, size, pool) => {
    for (let k = 0, tries = 0; k < n && tries < 4000; tries++) {
      const x = range(-0.85, 0.85), y = range(-0.9, 0.9);
      if (x * x / 0.75 + y * y / 0.85 > 1) continue;
      if (glyphs.some(g => Math.hypot(g.x - x, g.y - y) < minD * (g.size + size[1]) / 0.9)) continue;
      glyphs.push({ ch: pool[Math.floor(rnd() * pool.length)], x, y, z: range(-1, 1), size: range(size[0], size[1]), rot: range(-0.55, 0.55), ph: range(0, 6.28), pop: -1e9 });
      k++;
    }
  };
  placeGlyphs(7, 0.5, [0.55, 0.85], BIG);
  placeGlyphs(12, 0.45, [0.22, 0.38], MID);
  placeGlyphs(26, 0.4, [0.08, 0.16], SMALL);
  glyphs.sort((a, b) => a.z - b.z);
  const loopPath = (cx, cy, rx, ry, turns, wob, n) => {
    const pts = [], off = range(0, 6);
    for (let i = 0; i <= n; i++) {
      const a = i / n * Math.PI * 2 * turns;
      const f = 1 + Math.sin(a * 3 + off) * wob + range(-wob, wob) * 0.5;
      pts.push([cx + Math.cos(a) * rx * f, cy + Math.sin(a) * ry * f]);
    }
    return pts;
  };
  const scribbles = [{ pts: loopPath(0, 0, 0.8, 0.96, 1.15, 0.03, 90), w: 1.6 }, { pts: loopPath(0.02, 0.01, 0.78, 0.93, 1.05, 0.05, 90), w: 1.1 }];
  for (let i = 0; i < 4; i++) scribbles.push({ pts: loopPath(range(-0.4, 0.4), range(-0.5, 0.5), range(0.12, 0.26), range(0.1, 0.22), range(1.6, 2.6), 0.12, 70), w: 1 });

  let mx = 0, my = 0, yaw = 0, pitch = 0;
  addEventListener('pointermove', (e) => { mx = e.clientX / innerWidth * 2 - 1; my = e.clientY / innerHeight * 2 - 1; }, { passive: true });
  const words = [];
  let nextSwap = 0;
  const v = new THREE.Vector3(), v2 = new THREE.Vector3();
  const toScreen = (vec) => { vec.project(camera); return [(vec.x + 1) / 2 * W, (1 - vec.y) / 2 * H]; };
  const head = { x: 0, y: 0, r: 0 };

  function drawCloud(t) {
    figure.updateMatrixWorld();
    const [cx, cy] = toScreen(figure.localToWorld(v.set(0, 1.75, 0.3)));
    const [, ty] = toScreen(figure.localToWorld(v2.set(0, 1.75 + 2.6, 0.3)));
    const R = cy - ty;
    Object.assign(head, { x: cx, y: cy, r: R });
    const k8 = Math.floor(t / 125);
    if (!still && t > nextSwap) {
      const g = glyphs[Math.floor(rnd() * glyphs.length)];
      if (g.size < 0.4) { const pool = g.size < 0.2 ? SMALL : MID; g.ch = pool[Math.floor(rnd() * pool.length)]; g.pop = t; }
      nextSwap = t + range(500, 1400);
    }
    const rx = R * 0.82 * (1 - Math.abs(yaw) * 0.12), ry = R;
    const px = (x, z) => cx + x * rx + z * yaw * R * 0.35;
    ctx.lineCap = ctx.lineJoin = 'round';
    scribbles.forEach((s, si) => {
      ctx.beginPath();
      s.pts.forEach(([x, y], i) => {
        const j = (hash(i, si, k8) - 0.5) * R * 0.012;
        const X = px(x, 0) + j, Y = cy + y * ry + j;
        if (i) ctx.lineTo(X, Y); else ctx.moveTo(X, Y);
      });
      ctx.strokeStyle = C.ink;
      ctx.lineWidth = s.w;
      ctx.globalAlpha = 0.8;
      ctx.stroke();
    });
    ctx.globalAlpha = 1;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    glyphs.forEach((g, gi) => {
      const pop = 1 + 0.35 * Math.exp(-(t - g.pop) / 160);
      const size = g.size * R * 1.25 * pop;
      const X = px(g.x, g.z) + Math.sin(t * 0.0012 + g.ph) * R * 0.012;
      const Y = cy + g.y * ry + Math.sin(t * 0.0014 + g.ph) * R * 0.015;
      const red = REDSET.has(g.ch) || (t - g.pop < 300 && g.size < 0.2);
      ctx.save();
      ctx.translate(X, Y);
      ctx.rotate(g.rot + Math.sin(t * 0.0009 + g.ph) * 0.05);
      ctx.font = `${size}px "Permanent Marker", cursive`;
      ctx.lineWidth = size * 0.09;
      ctx.strokeStyle = C.paper;
      ctx.strokeText(g.ch, 0, 0);
      ctx.fillStyle = red ? C.red : C.ink;
      ctx.fillText(g.ch, 0, 0);
      ctx.lineWidth = Math.max(0.8, size * 0.012);
      ctx.strokeStyle = red ? C.red : C.ink;
      ctx.strokeText(g.ch, (hash(gi, 1, k8) - 0.5) * size * 0.03, (hash(gi, 2, k8) - 0.5) * size * 0.03);
      ctx.restore();
    });
  }

  function frame(t) {
    if (!buf) return;
    C = colors();
    isDark = dark();
    yaw += (mx * 0.5 - yaw) * (still ? 1 : 0.08);
    pitch += (my * 0.12 - pitch) * (still ? 1 : 0.08);
    bust.rotation.set(pitch * 0.3, yaw * 0.25, 0);
    renderer.setRenderTarget(target);
    renderer.render(scene, camera);
    renderer.setRenderTarget(null);
    renderer.readRenderTargetPixels(target, 0, 0, cols, rows, buf);
    const at = (x, y) => ((rows - 1 - y) * cols + x) * 4;
    const has = (x, y) => buf[at(x, y) + 3] > 0;
    for (let k = words.length - 1; k >= 0; k--) if (t > words[k].until) words.splice(k, 1);
    for (let tries = 0; tries < 6 && words.length < 7; tries++) {
      const text = ERR[Math.floor(rnd() * ERR.length)];
      const x = Math.floor(rnd() * (cols - text.length)), y = Math.floor(rnd() * rows);
      let ok = words.every(w => w.y !== y || x > w.x + w.text.length + 1 || x + text.length + 1 < w.x);
      for (let k = 0; k < text.length && ok; k++) ok = has(x + k, y);
      if (ok) words.push({ x, y, text, until: t + 900 + rnd() * 2400 });
    }
    ctx.clearRect(0, 0, W, H);
    ctx.textAlign = 'left';
    ctx.textBaseline = 'top';
    ctx.font = `500 ${FONT}px "JetBrains Mono", ui-monospace, monospace`;
    const k8 = Math.floor(t / 125);
    const ink = [], qm = [];
    const taken = new Set();
    words.forEach(w => { for (let k = 0; k < w.text.length; k++) taken.add((w.x + k) + w.y * cols); });
    for (let y = 0; y < rows; y++) {
      for (let x = 0; x < cols; x++) {
        const i = at(x, y);
        if (!buf[i + 3] || taken.has(x + y * cols)) continue;
        const lum = (buf[i] + buf[i + 1]) / 510;
        const d = isDark ? Math.pow(lum, 1.25) : 1 - Math.pow(lum, 0.8) * 0.92;
        const ch = RAMP[Math.max(1, Math.min(RAMP.length - 1, Math.round(d * (RAMP.length - 1) + (hash(x, y, k8) - 0.5) * 0.9)))];
        (ch === '?' ? qm : ink).push(ch, x, y);
      }
    }
    const draw = (arr, color) => { ctx.fillStyle = color; for (let k = 0; k < arr.length; k += 3) ctx.fillText(arr[k], arr[k + 1] * CW, arr[k + 2] * CH); };
    draw(ink, C.body);
    ctx.font = `700 ${FONT}px "JetBrains Mono", ui-monospace, monospace`;
    draw(qm, C.ink);
    ctx.fillStyle = C.red;
    words.forEach(w => ctx.fillText(w.text, w.x * CW, w.y * CH));
    drawCloud(t);
  }

  await Promise.allSettled([document.fonts.load('40px "Permanent Marker"'), document.fonts.load('500 9px "JetBrains Mono"')]);
  let running = !still, last = 0;
  const loop = (now) => {
    if (!running) return;
    requestAnimationFrame(loop);
    if (now - last < 33 || document.hidden) return;
    last = now;
    frame(now);
  };
  if (still) frame(0); else requestAnimationFrame(loop);
  return {
    head,
    resize: () => { resize(); if (still) frame(0); },
    stop: () => { running = false; },
    start: () => { if (running || still) return; running = true; requestAnimationFrame(loop); },
  };
}
