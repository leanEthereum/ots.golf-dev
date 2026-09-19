(function () {
  'use strict';
  // The iris is the forest scheme; each cycle lights one real signature and lets the verifier run.
  //
  // A signature is a uniform element of the scheme's disclosure family (Cuts.lean), the cuts of
  // cost 103 with at most 42 revealed values, of three shapes (revealed subtrees, revealed groups,
  // chain cost). The shape is drawn by its share of the family, the digests uniformly, and the
  // chain positions exactly through the counting table (doubles carry the ratios).
  //
  // Verification is drawn as current: it leaves every revealed value at once and runs along the
  // edges the verifier hashes, all at one constant speed. A chain bead lights when the current
  // reaches it; a group, subtree or the root lights when the last of its inputs arrives, and only
  // then does the current leave it (until then it holds a faint steady glow). When the
  // root (the pupil) is reached, the eye blinks, and a fresh signature is lit while it is closed.
  var svg = document.querySelector('svg.scheme-art');
  if (!svg) return;
  var NS = 'http://www.w3.org/2000/svg';
  var LEN = +svg.dataset.len, SUBTREES = 6, GROUPS = 18, CHAINS = 54;
  var SHAPES = svg.dataset.shapes.split(';').map(function (t) { return t.split(',').map(Number); });
  var els = Array.prototype.slice.call(svg.querySelectorAll('[data-r]'));
  var TOP = Math.max.apply(null, SHAPES.map(function (t) { return t[2]; }));
  var ways = [[]], n, s, c;                        // ways[n][s]: s hashes on n chains, each 0..LEN
  for (s = 0; s <= TOP; s++) ways[0].push(s === 0 ? 1 : 0);
  for (n = 1; n <= CHAINS; n++) { ways.push([]); for (s = 0; s <= TOP; s++) {
    var acc = 0; for (c = 0; c <= Math.min(LEN, s); c++) acc += ways[n - 1][s - c]; ways[n].push(acc); } }
  function choose(m, k) { var r = 1; for (var i = 1; i <= k; i++) r = r * (m - k + i) / i; return r; }
  var weights = SHAPES.map(function (t) { return choose(SUBTREES, t[0]) * choose(GROUPS - 3 * t[0], t[1]) * ways[CHAINS - 9 * t[0] - 3 * t[1]][t[2]]; });
  var total = weights.reduce(function (x, y) { return x + y; }, 0);
  function pick(list, k) {                         // k distinct elements, uniformly
    var pool = list.slice(), out = [];
    for (var i = 0; i < k; i++) out.push(pool.splice(Math.floor(Math.random() * pool.length), 1)[0]);
    return out;
  }
  function sample() {
    var r = Math.random() * total, shape = SHAPES[SHAPES.length - 1], i, j, k;
    for (i = 0; i < SHAPES.length; i++) { if (r < weights[i]) { shape = SHAPES[i]; break; } r -= weights[i]; }
    var all = []; for (i = 0; i < SUBTREES; i++) all.push(i);
    var revE = {}; pick(all, shape[0]).forEach(function (l) { revE[l] = true; });
    var under = []; for (j = 0; j < GROUPS; j++) if (!revE[Math.floor(j / 3)]) under.push(j);
    var revG = {}; pick(under, shape[1]).forEach(function (g) { revG[g] = true; });
    var chains = []; for (k = 0; k < CHAINS; k++) { j = Math.floor(k / 3); if (!revE[Math.floor(j / 3)] && !revG[j]) chains.push(k); }
    var t = {}, budget = shape[2];
    chains.forEach(function (k, idx) {
      var left = chains.length - idx, x = Math.random() * ways[left][budget], c = 0;
      while (c < Math.min(LEN, budget) && x >= ways[left - 1][budget - c]) { x -= ways[left - 1][budget - c]; c++; }
      t[k] = LEN - c; budget -= c;
    });
    return { revE: revE, revG: revG, t: t };
  }

  // ---- lighting a signature --------------------------------------------------------------
  function set(el, c, wait) {
    var cl = el.classList;
    if (!cl.contains(c)) { cl.remove('revealed', 'recomputed', 'untouched'); cl.add(c); }
    cl.toggle('wait', !!wait && c === 'recomputed');
    cl.remove('fed');
  }
  function light(cut, wait) {
    els.forEach(function (el) {
      var d = el.dataset, k, tk, j;
      if (d.r === 'bead' || d.r === 'cedge') {
        k = +d.k; tk = cut.t[k];
        if (tk === undefined) return set(el, 'untouched');
        if (d.r === 'bead') return set(el, +d.t === tk ? 'revealed' : +d.t > tk ? 'recomputed' : 'untouched', wait);
        return set(el, +d.t > tk ? 'recomputed' : 'untouched', wait);
      }
      if (d.r === 'g' || d.r === 'tip') {
        j = +d.g;
        var hidden = cut.revE[Math.floor(j / 3)];
        if (d.r === 'g') return set(el, hidden ? 'untouched' : cut.revG[j] ? 'revealed' : 'recomputed', wait);
        return set(el, hidden || cut.revG[j] ? 'untouched' : 'recomputed', wait);
      }
      if (d.r === 's') return set(el, cut.revE[+d.s] ? 'revealed' : 'recomputed', wait);
      if (d.r === 'gedge') return set(el, cut.revE[+d.s] ? 'untouched' : 'recomputed', wait);
      if (d.r === 'redge') return set(el, 'recomputed', wait);
    });
  }

  // ---- the drawing's geometry ------------------------------------------------------------
  var CX = 430, CY = 280, PUPIL = 46;
  var bead = [], cedge = [], tip = [], gNode = [], gEdge = [], sNode = [], rEdge = [];
  els.forEach(function (el) {
    var d = el.dataset;
    if (d.r === 'bead') (bead[+d.k] = bead[+d.k] || [])[+d.t] = el;
    else if (d.r === 'cedge') (cedge[+d.k] = cedge[+d.k] || [])[+d.t] = el;
    else if (d.r === 'tip') tip[+d.k] = el;
    else if (d.r === 'g') gNode[+d.g] = el;
    else if (d.r === 'gedge') gEdge[+d.g] = el;
    else if (d.r === 's') sNode[+d.s] = el;
    else if (d.r === 'redge') rEdge[+d.s] = el;
  });
  function num(el, a) { return +el.getAttribute(a); }
  function at(el) {
    if (el.dataset.x) return { x: +el.dataset.x, y: +el.dataset.y, r: 3.4 };
    return { x: num(el, 'cx'), y: num(el, 'cy'), r: num(el, 'r') };
  }

  // ---- motion constants --------------------------------------------------------------------
  var SPEED = 28;                 // SVG units per second: the one speed of every current, always
  var OPEN = 300, PRE = 800;      // the eye opens, the revealed values glint, then the current starts
  var HOLD = 1100;                // the root glows this long before the eye closes
  var CLOSE = 150, SHUT = 120;    // a blink closes quickly and stays shut for a moment
  var TAIL_CORE = 6, TAIL_GLOW = 20;
  var LID_OPEN = [4, -4, 574, 578], LID_SHUT = [330, 326, 326, 330];   // mirrors scheme_art.py

  var overlay = svg.querySelector('[data-current]');
  var rootGlow = svg.querySelector('[data-root-glow]');
  var aperture = svg.querySelector('[data-eye-aperture]');
  var lidEls = {};
  Array.prototype.forEach.call(svg.querySelectorAll('[data-lid]'), function (el) { lidEls[el.dataset.lid] = el; });
  function mk(tag, attrs, parent) {
    var el = document.createElementNS(NS, tag);
    for (var a in attrs) el.setAttribute(a, attrs[a]);
    if (parent) parent.appendChild(el);
    return el;
  }
  var edgeLayer = overlay && mk('g', {}, overlay), pulseLayer = overlay && mk('g', {}, overlay);
  var pulses = [], nextPulse = 0;
  if (overlay) for (var p = 0; p < 96; p++)
    pulses.push({ el: mk('circle', { 'class': 'pulse', r: 0, display: 'none' }, pulseLayer), end: 0 });

  function openEye(a) {
    var v = LID_SHUT.map(function (sh, i) { return sh + (LID_OPEN[i] - sh) * a; });
    var f = function (x) { return Math.round(x * 100) / 100; };
    var upper = 'M 22 284 C 180 ' + f(v[0]) + ' 650 ' + f(v[1]) + ' 838 272';
    var lower = 'M 838 272 C 660 ' + f(v[2]) + ' 200 ' + f(v[3]) + ' 22 284';
    aperture.setAttribute('d', upper + ' ' + lower + ' Z');
    lidEls.upper.setAttribute('d', upper);
    lidEls.lower.setAttribute('d', lower);
    lidEls['lid-upper'].setAttribute('d', upper + ' C 650 ' + f(v[1] - 12) + ' 180 ' + f(v[0] - 12) + ' 22 284 Z');
    lidEls['lid-lower'].setAttribute('d', lower + ' C 200 ' + f(v[3] + 5) + ' 660 ' + f(v[2] + 5) + ' 838 272 Z');
    var c = -23 + 34 * (1 - a);
    lidEls.crease.setAttribute('d', 'M 118 216 C 250 ' + f(c) + ' 610 ' + f(c - 6) + ' 746 204 C 610 ' + f(c - 2.5) + ' 250 ' + f(c + 3.5) + ' 118 216 Z');
  }

  // ---- one verification, planned: every edge's start time, every node's lighting time ------
  function plan(cut) {
    var edges = [], events = [], frag = document.createDocumentFragment();
    function edge(el, t0, toPupil) {
      var x1 = num(el, 'x1'), y1 = num(el, 'y1'), x2 = num(el, 'x2'), y2 = num(el, 'y2');
      var len = Math.hypot(x2 - x1, y2 - y1);
      if (toPupil) { var k = (len - PUPIL) / len; x2 = x1 + (x2 - x1) * k; y2 = y1 + (y2 - y1) * k; len -= PUPIL; }
      var g = mk('g', { display: 'none' }, frag), line = { x1: x1, y1: y1, x2: x2, y2: y2 };
      var e = { el: el, t0: t0, len: len, x1: x1, y1: y1, dx: x2 - x1, dy: y2 - y1, g: g, done: false, on: false,
        trace: mk('line', Object.assign({ 'class': 'trace' }, line), g),
        glow: mk('line', Object.assign({ 'class': 'glow' }, line), g),
        core: mk('line', Object.assign({ 'class': 'core' }, line), g),
        spark: mk('circle', { 'class': 'spark', fill: 'url(#art-spark)', r: 0, cx: x1, cy: y1 }, g) };
      edges.push(e);
      return t0 + len / SPEED * 1000;
    }
    function node(el, t, kind) { var q = at(el); events.push({ t: t, el: el, x: q.x, y: q.y, r: q.r, kind: kind }); }
    var gT = [], sT = [], j, k, l, t, arrivals;
    for (j = 0; j < GROUPS; j++) {
      if (cut.revE[Math.floor(j / 3)]) continue;
      if (cut.revG[j]) { gT[j] = 0; node(gNode[j], 0, 'gold'); continue; }
      arrivals = [];
      for (k = 3 * j; k < 3 * j + 3; k++) {
        var time = 0, tk = cut.t[k];
        node(bead[k][tk], 0, 'gold');
        for (t = tk + 1; t <= LEN; t++) { time = edge(cedge[k][t], time); node(bead[k][t], time, 'bead'); }
        arrivals.push(edge(tip[k], time));
      }
      gT[j] = Math.max.apply(null, arrivals);
      arrivals.forEach(function (a) { if (a < gT[j]) node(gNode[j], a, 'touch'); });
      node(gNode[j], gT[j], 'node');
    }
    for (l = 0; l < SUBTREES; l++) {
      if (cut.revE[l]) { sT[l] = 0; node(sNode[l], 0, 'gold'); continue; }
      arrivals = [];
      for (j = 3 * l; j < 3 * l + 3; j++) arrivals.push(edge(gEdge[j], gT[j]));
      sT[l] = Math.max.apply(null, arrivals);
      arrivals.forEach(function (a) { if (a < sT[l]) node(sNode[l], a, 'touch'); });
      node(sNode[l], sT[l], 'node');
    }
    var root = 0;
    for (l = 0; l < SUBTREES; l++) root = Math.max(root, edge(rEdge[l], sT[l], true));
    events.forEach(function (ev) { if (ev.kind === 'gold') ev.t = -PRE + 80 + Math.random() * (PRE - 260); });
    events.sort(function (a, b) { return a.t - b.t; });
    return { edges: edges, events: events, root: root, frag: frag };
  }

  function pulse(now, x, y, r0, r1, dur, width, gold) {
    var q = pulses[nextPulse]; nextPulse = (nextPulse + 1) % pulses.length;
    q.x = x; q.y = y; q.r0 = r0; q.r1 = r1; q.t0 = now; q.end = now + dur; q.w = width;
    q.el.setAttribute('cx', x); q.el.setAttribute('cy', y);
    q.el.classList.toggle('gold', !!gold);
    q.el.removeAttribute('display');
  }
  function drawPulses(now) {
    pulses.forEach(function (q) {
      if (!q.end) return;
      var p = (now - q.t0) / (q.end - q.t0);
      if (p >= 1) { q.end = 0; q.el.setAttribute('display', 'none'); return; }
      var e = 1 - (1 - p) * (1 - p);
      q.el.setAttribute('r', (q.r0 + (q.r1 - q.r0) * e).toFixed(2));
      q.el.setAttribute('stroke-width', (q.w * (1 - .6 * p)).toFixed(2));
      q.el.setAttribute('stroke-opacity', ((1 - p) * (1 - p) * .9).toFixed(3));
    });
  }

  // ---- the cycle -----------------------------------------------------------------------------
  var motion = window.matchMedia('(prefers-reduced-motion: reduce)');
  var cur = null, cycle = 0, clock = 0, last, frame, visible = true, eye = 'open';
  function setEye(state) { if (eye !== state) { eye = state; svg.dataset.eye = state; } }
  function clearOverlay() {
    if (!overlay) return;
    while (edgeLayer.firstChild) edgeLayer.removeChild(edgeLayer.firstChild);
    pulses.forEach(function (q) { q.end = 0; q.el.setAttribute('display', 'none'); });
    rootGlow.setAttribute('opacity', 0);
  }
  function newCycle() {                            // only ever called while the eye is shut
    clearOverlay();
    var cut = sample();
    light(cut, !!overlay);
    if (!overlay) return;
    cur = plan(cut);
    edgeLayer.appendChild(cur.frag);
    cur.next = 0;
    cur.start = clock;                             // the eye starts opening now
    cur.go = clock + OPEN + PRE;                   // the current leaves the revealed values
    cur.rootAt = cur.go + cur.root;
    cur.blinkAt = cur.rootAt + HOLD;
    cur.rooted = false;
    svg.dataset.cycle = ++cycle;
  }
  function smooth(x) { x = Math.min(1, Math.max(0, x)); return x * x * (3 - 2 * x); }
  function tick(now) {
    frame = requestAnimationFrame(tick);
    clock += Math.min(50, Math.max(0, now - (last === undefined ? now : last)));
    last = now;
    var c = cur, i, e, u, a, b, tau;
    if (!c) return;
    // the lids
    if (clock < c.start + OPEN) { openEye(smooth((clock - c.start) / OPEN)); setEye('opening'); }
    else if (clock < c.blinkAt) { if (eye !== 'open') { openEye(1); setEye('open'); } }
    else if (clock < c.blinkAt + CLOSE) { openEye(1 - smooth((clock - c.blinkAt) / CLOSE)); setEye('closing'); }
    else {
      openEye(0); setEye('closed');
      if (clock >= c.blinkAt + CLOSE + SHUT) newCycle();
      return;
    }
    tau = clock - c.go;
    // nodes light as their inputs arrive
    while (c.next < c.events.length && c.events[c.next].t <= tau) {
      e = c.events[c.next++];
      if (e.kind === 'gold') pulse(clock, e.x, e.y, e.r + .5, e.r + 8, 1100, 1.4, true);
      else if (e.kind === 'bead') { e.el.classList.remove('wait'); pulse(clock, e.x, e.y, e.r, e.r + 4.5, 650, 1); }
      else if (e.kind === 'touch') { e.el.classList.add('fed'); pulse(clock, e.x, e.y, e.r, e.r + 4, 500, .8); }
      else { e.el.classList.remove('wait', 'fed'); pulse(clock, e.x, e.y, e.r, e.r + 10, 900, 1.6); }
    }
    // the current along each edge: a lit trace behind, a glowing tail and a spark at the head
    for (i = 0; i < c.edges.length; i++) {
      e = c.edges[i];
      u = (tau - e.t0) * SPEED / 1000;
      if (u <= 0 || u >= e.len + TAIL_GLOW) {
        if (e.on) { e.on = false; e.g.setAttribute('display', 'none'); }
        if (u > 0 && !e.done) { e.done = true; e.el.classList.remove('wait'); }
        continue;
      }
      if (!e.on) { e.on = true; e.g.removeAttribute('display'); }
      if (u < e.len) {
        e.trace.setAttribute('stroke-dasharray', u.toFixed(2) + ' 999');
        e.spark.setAttribute('cx', (e.x1 + e.dx * u / e.len).toFixed(2));
        e.spark.setAttribute('cy', (e.y1 + e.dy * u / e.len).toFixed(2));
        e.spark.setAttribute('r', (4.4 + Math.random() * 1.4).toFixed(2));
      } else if (!e.done) {
        e.done = true; e.el.classList.remove('wait');
        e.trace.setAttribute('display', 'none'); e.spark.setAttribute('display', 'none');
      }
      b = Math.min(u, e.len);
      a = Math.max(0, u - TAIL_CORE);
      e.core.setAttribute('stroke-dasharray', Math.max(0, b - a).toFixed(2) + ' 999');
      e.core.setAttribute('stroke-dashoffset', (-a).toFixed(2));
      e.core.setAttribute('stroke-opacity', (.75 + Math.random() * .25).toFixed(2));
      a = Math.max(0, u - TAIL_GLOW);
      e.glow.setAttribute('stroke-dasharray', Math.max(0, b - a).toFixed(2) + ' 999');
      e.glow.setAttribute('stroke-dashoffset', (-a).toFixed(2));
    }
    // the root: the pupil's rim glows once every input has arrived
    if (clock >= c.rootAt) {
      if (!c.rooted) { c.rooted = true; pulse(clock, CX, CY, PUPIL, PUPIL + 34, 1400, 3); }
      var r = (clock - c.rootAt) / 1000;
      rootGlow.setAttribute('opacity', (r < .35 ? smooth(r / .35) : .62 + .38 * Math.exp(-(r - .35) * 2.2)).toFixed(3));
    }
    drawPulses(clock);
  }
  function stopMotion() { cancelAnimationFrame(frame); frame = undefined; last = undefined; }
  function updateMotion() {
    var still = motion.matches || !overlay || !aperture;
    if (still) {
      stopMotion(); cur = null; clearOverlay();
      light(sample(), false);
      if (aperture) openEye(1);
      setEye('open');
      return;
    }
    if (document.hidden || !visible) { stopMotion(); return; }
    if (!cur) { openEye(0); setEye('closed'); newCycle(); }
    if (frame === undefined) frame = requestAnimationFrame(tick);
  }
  motion.addEventListener('change', function () { cur = null; updateMotion(); });
  document.addEventListener('visibilitychange', updateMotion);
  if ('IntersectionObserver' in window) new IntersectionObserver(function (entries) {
    visible = entries[entries.length - 1].isIntersecting; updateMotion();
  }).observe(svg);
  updateMotion();
})();
