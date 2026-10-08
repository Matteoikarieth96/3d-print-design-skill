/* Local STL viewer for the 3d-print-design skill.
 * Loads manifest.json from the local server, draws every listed STL on a bed
 * grid with orbit controls, a section plane, a bounding-box readout and a
 * dark/light theme. Uses only three.js r128 (core) from cdnjs; the STL parser
 * and the orbit control are small built-ins written for this file, so no other
 * library is fetched. Text from files is placed with textContent only.
 * MIT licence, see LICENSE in the repository.
 */
(function () {
  'use strict';

  var SAFE_FILE = /^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/;
  var HEX = /^#[0-9a-fA-F]{6}$/;
  var MAX_TRIS = 5000000;
  var VIEWS = {
    iso: [-Math.PI / 3, Math.PI / 3],
    top: [-Math.PI / 2, 0.0001],
    front: [-Math.PI / 2, Math.PI / 2],
    right: [0, Math.PI / 2]
  };

  var params = new URLSearchParams(window.location.search);
  var body = document.body;
  var statusEl = document.getElementById('status');

  function setStatus(text) { statusEl.textContent = text; }
  function el(tag, text) { var e = document.createElement(tag); if (text !== undefined) e.textContent = text; return e; }
  function fmt(v) { return (Math.round(v * 10) / 10).toFixed(1); }

  // ---------------------------------------------------------------- theme
  var themeParam = params.get('theme');
  function storedTheme() { try { return window.localStorage.getItem('print-preview-theme'); } catch (e) { return null; } }
  function storeTheme(t) { try { window.localStorage.setItem('print-preview-theme', t); } catch (e) { /* private mode */ } }
  var initialTheme = (themeParam === 'dark' || themeParam === 'light') ? themeParam : storedTheme();
  if (initialTheme === 'dark' || initialTheme === 'light') document.documentElement.setAttribute('data-theme', initialTheme);
  function cssVar(name) { return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || '#888888'; }
  function isDark() {
    var t = document.documentElement.getAttribute('data-theme');
    if (t) return t === 'dark';
    return window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
  }
  if (params.get('ui') === '0') body.classList.add('no-ui');

  // ---------------------------------------------------------------- data
  function loadManifest() {
    return fetch('/manifest.json', { cache: 'no-store' }).then(function (r) {
      if (!r.ok) throw new Error('manifest.json: HTTP ' + r.status);
      return r.json();
    }).then(function (m) {
      var bed = Array.isArray(m.bed) && m.bed.length === 3 ? m.bed.map(Number) : [220, 220, 250];
      if (!bed.every(function (v) { return isFinite(v) && v >= 10 && v <= 3000; })) bed = [220, 220, 250];
      var parts = (Array.isArray(m.parts) ? m.parts : []).filter(function (p) {
        return p && typeof p.file === 'string' && SAFE_FILE.test(p.file) && /\.stl$/i.test(p.file);
      }).map(function (p, i) {
        return {
          file: p.file,
          name: typeof p.name === 'string' ? p.name.slice(0, 80) : p.file,
          color: typeof p.color === 'string' && HEX.test(p.color) ? p.color : '#4f8cff',
          index: i
        };
      });
      return { bed: bed, parts: parts };
    });
  }

  function parseSTL(buf) {
    var dv = new DataView(buf);
    if (buf.byteLength >= 84) {
      var n = dv.getUint32(80, true);
      if (84 + n * 50 === buf.byteLength) {
        if (n > MAX_TRIS) throw new Error('too many triangles');
        var out = new Float32Array(n * 9);
        for (var i = 0; i < n; i++) {
          var o = 84 + i * 50 + 12;
          for (var k = 0; k < 9; k++) out[i * 9 + k] = dv.getFloat32(o + k * 4, true);
        }
        return out;
      }
    }
    var text = new TextDecoder('ascii').decode(new Uint8Array(buf));
    var re = /vertex\s+([-+]?[\d.]+(?:[eE][-+]?\d+)?)\s+([-+]?[\d.]+(?:[eE][-+]?\d+)?)\s+([-+]?[\d.]+(?:[eE][-+]?\d+)?)/g;
    var vals = [];
    var m;
    while ((m = re.exec(text)) !== null) {
      vals.push(parseFloat(m[1]), parseFloat(m[2]), parseFloat(m[3]));
      if (vals.length > MAX_TRIS * 9) throw new Error('too many triangles');
    }
    return new Float32Array(vals.slice(0, vals.length - (vals.length % 9)));
  }

  // ---------------------------------------------------------------- fallback (no WebGL / offline)
  function showFallback(reason, parts) {
    body.dataset.render = 'fallback';
    var box = document.getElementById('fallback');
    box.hidden = false;
    document.getElementById('fallback-msg').textContent = reason +
      ' Showing flat SVG pictures instead; the STL files are unchanged and open in any slicer.';
    var imgs = document.getElementById('fallback-imgs');
    (parts || []).forEach(function (p) {
      var stem = p.file.replace(/\.stl$/i, '');
      if (!SAFE_FILE.test(stem)) return;
      var img = el('img');
      img.alt = p.name;
      img.src = '/preview/' + encodeURIComponent(stem) + '.svg';
      imgs.appendChild(img);
    });
    setStatus(reason);
  }

  // ---------------------------------------------------------------- start
  loadManifest().then(function (manifest) {
    fillPartList(manifest.parts);
    if (!manifest.parts.length) { setStatus('No STL files in the served folder yet.'); body.dataset.render = 'empty'; return; }
    if (typeof window.THREE === 'undefined') {
      showFallback('three.js could not be loaded (offline or blocked).', manifest.parts);
      return;
    }
    var renderer;
    try {
      renderer = new THREE.WebGLRenderer({ antialias: true, preserveDrawingBuffer: true });
      if (!renderer.getContext()) throw new Error('no context');
    } catch (e) {
      showFallback('WebGL is not available in this browser.', manifest.parts);
      return;
    }
    startViewer(renderer, manifest);
  }).catch(function (err) {
    body.dataset.render = 'error';
    setStatus('Could not load the parts: ' + err.message);
  });

  function fillPartList(parts) {
    var ul = document.getElementById('parts');
    parts.forEach(function (p) {
      var li = el('li');
      var cb = el('input');
      cb.type = 'checkbox';
      cb.checked = true;
      cb.dataset.index = String(p.index);
      cb.setAttribute('aria-label', 'Show ' + p.name);
      var sw = el('span');
      sw.className = 'swatch';
      sw.style.background = p.color;
      li.appendChild(cb);
      li.appendChild(sw);
      li.appendChild(el('span', p.name));
      ul.appendChild(li);
    });
  }

  function startViewer(renderer, manifest) {
    var bed = manifest.bed;
    var stage = document.getElementById('stage');
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.localClippingEnabled = true;
    stage.appendChild(renderer.domElement);

    var scene = new THREE.Scene();
    var camera = new THREE.PerspectiveCamera(35, 1, 0.1, 50000);
    camera.up.set(0, 0, 1);
    scene.add(new THREE.HemisphereLight(0xffffff, 0x445566, 0.75));
    scene.add(new THREE.AmbientLight(0xffffff, 0.18));
    var sun = new THREE.DirectionalLight(0xffffff, 0.7);
    scene.add(sun);
    scene.add(sun.target);
    var fill = new THREE.DirectionalLight(0xffffff, 0.3);
    scene.add(fill);
    scene.add(fill.target);

    // bed, grid, build volume -------------------------------------------
    var bedGroup = new THREE.Group();
    scene.add(bedGroup);
    var bedMat = new THREE.MeshBasicMaterial({ color: cssVar('--bed') });
    var bedMesh = new THREE.Mesh(new THREE.PlaneGeometry(bed[0], bed[1]), bedMat);
    bedMesh.position.set(bed[0] / 2, bed[1] / 2, -0.05);
    bedGroup.add(bedMesh);
    function gridLines(step, major) {
      var pts = [];
      for (var x = 0; x <= bed[0] + 1e-6; x += step) {
        if (major || Math.round(x) % 50 !== 0) pts.push(x, 0, 0, x, bed[1], 0);
      }
      for (var y = 0; y <= bed[1] + 1e-6; y += step) {
        if (major || Math.round(y) % 50 !== 0) pts.push(0, y, 0, bed[0], y, 0);
      }
      var g = new THREE.BufferGeometry();
      g.setAttribute('position', new THREE.Float32BufferAttribute(pts, 3));
      return g;
    }
    var minorMat = new THREE.LineBasicMaterial({ color: cssVar('--grid') });
    var majorMat = new THREE.LineBasicMaterial({ color: cssVar('--grid-major') });
    bedGroup.add(new THREE.LineSegments(gridLines(10, false), minorMat));
    bedGroup.add(new THREE.LineSegments(gridLines(50, true), majorMat));
    var volume = new THREE.LineSegments(
      new THREE.EdgesGeometry(new THREE.BoxGeometry(bed[0], bed[1], bed[2])),
      new THREE.LineBasicMaterial({ color: cssVar('--grid-major') }));
    volume.position.set(bed[0] / 2, bed[1] / 2, bed[2] / 2);
    volume.visible = false;
    bedGroup.add(volume);

    // parts -----------------------------------------------------------------
    var partsGroup = new THREE.Group();
    scene.add(partsGroup);
    var clipPlane = new THREE.Plane(new THREE.Vector3(0, -1, 0), 0);
    var meshes = [];
    var edgeLines = [];
    var framePending = false;
    function requestRender() {  // render on demand: no idle animation loop
      if (framePending) return;
      framePending = true;
      window.requestAnimationFrame(function () { framePending = false; renderer.render(scene, camera); });
    }

    function applyTheme() {
      scene.background = new THREE.Color(cssVar('--bg'));
      bedMat.color.set(cssVar('--bed'));
      minorMat.color.set(cssVar('--grid'));
      majorMat.color.set(cssVar('--grid-major'));
      volume.material.color.set(cssVar('--grid-major'));
      edgeLines.forEach(function (l) { l.material.color.set(isDark() ? 0x0b0e13 : 0x1d2430); });
      requestRender();
    }

    var loaded = 0;
    var failed = 0;
    setStatus('Loading ' + manifest.parts.length + ' part(s)...');
    var jobs = manifest.parts.map(function (p) {
      return fetch('/files/' + encodeURIComponent(p.file), { cache: 'no-store' }).then(function (r) {
        if (!r.ok) throw new Error(p.file + ': HTTP ' + r.status);
        return r.arrayBuffer();
      }).then(function (buf) {
        var pos = parseSTL(buf);
        if (pos.length < 9) throw new Error(p.file + ': no triangles');
        var geom = new THREE.BufferGeometry();
        geom.setAttribute('position', new THREE.BufferAttribute(pos, 3));
        geom.computeVertexNormals();
        geom.computeBoundingBox();
        var mat = new THREE.MeshStandardMaterial({
          color: p.color, roughness: 0.6, metalness: 0.05, side: THREE.DoubleSide, clippingPlanes: [],
          polygonOffset: true, polygonOffsetFactor: 1, polygonOffsetUnits: 1  // keeps edge lines visible
        });
        var mesh = new THREE.Mesh(geom, mat);
        mesh.userData = { part: p, tris: pos.length / 9 };
        var edges = new THREE.LineSegments(new THREE.EdgesGeometry(geom, 35),
          new THREE.LineBasicMaterial({ color: 0x1d2430, transparent: true, opacity: 0.35, clippingPlanes: [] }));
        mesh.add(edges);
        edgeLines.push(edges);
        meshes[p.index] = mesh;
        partsGroup.add(mesh);
        loaded++;
      }).catch(function (err) {
        failed++;
        setStatus('Problem: ' + err.message);
      });
    });

    Promise.all(jobs).then(function () {
      if (!loaded) { body.dataset.render = 'error'; return; }
      // centre the whole assembly on the bed, keep its own z
      var box = new THREE.Box3().setFromObject(partsGroup);
      var cx = (box.min.x + box.max.x) / 2;
      var cy = (box.min.y + box.max.y) / 2;
      partsGroup.position.set(bed[0] / 2 - cx, bed[1] / 2 - cy, 0);
      fillDims();
      applyTheme();
      wireControls();
      var v = params.get('view');
      setView(VIEWS[v] ? v : 'iso');
      if (params.get('edges') === '0') { document.getElementById('edges').checked = false; toggleEdges(false); }
      var sec = params.get('section');
      if (sec === 'x' || sec === 'y' || sec === 'z') {
        document.getElementById('axis').value = sec;
        document.getElementById('section').checked = true;
        updateSection();
      }
      var floating = meshes.filter(Boolean).some(function (m) { return m.geometry.boundingBox.min.z > 0.01; });
      setStatus(loaded + ' part(s) loaded' + (failed ? ', ' + failed + ' failed' : '') +
        (floating ? '. Note: a part does not start at z = 0.' : '.'));
      resize();
      renderer.render(scene, camera);
      body.dataset.render = 'ok';
    });

    function fillDims() {
      var tbody = document.querySelector('#dims tbody');
      var all = new THREE.Box3();
      meshes.forEach(function (m) {
        if (!m) return;
        var b = m.geometry.boundingBox;
        all.union(b);
        var tr = el('tr');
        tr.appendChild(el('td', m.userData.part.name));
        tr.appendChild(el('td', fmt(b.max.x - b.min.x)));
        tr.appendChild(el('td', fmt(b.max.y - b.min.y)));
        tr.appendChild(el('td', fmt(b.max.z - b.min.z)));
        tbody.appendChild(tr);
      });
      if (meshes.filter(Boolean).length > 1) {
        var tr = el('tr');
        tr.appendChild(el('td', 'All'));
        tr.appendChild(el('td', fmt(all.max.x - all.min.x)));
        tr.appendChild(el('td', fmt(all.max.y - all.min.y)));
        tr.appendChild(el('td', fmt(all.max.z - all.min.z)));
        tbody.appendChild(tr);
      }
    }

    // orbit control (Z up) ---------------------------------------------------
    var orbit = { target: new THREE.Vector3(), r: 200, theta: VIEWS.iso[0], phi: VIEWS.iso[1] };
    function updateCamera() {
      var sp = Math.sin(orbit.phi);
      camera.position.set(
        orbit.target.x + orbit.r * sp * Math.cos(orbit.theta),
        orbit.target.y + orbit.r * sp * Math.sin(orbit.theta),
        orbit.target.z + orbit.r * Math.cos(orbit.phi));
      camera.lookAt(orbit.target);
      // key light from over the viewer's shoulder, fill light from the opposite side
      sun.position.copy(camera.position).add(new THREE.Vector3(0, 0, orbit.r * 0.6));
      sun.target.position.copy(orbit.target);
      fill.position.copy(orbit.target).sub(camera.position).add(orbit.target);
      fill.position.z = orbit.target.z + orbit.r * 0.4;
      fill.target.position.copy(orbit.target);
      sun.target.updateMatrixWorld();
      fill.target.updateMatrixWorld();
      requestRender();
    }
    function frame() {
      var box = new THREE.Box3().setFromObject(partsGroup);
      var sphere = box.getBoundingSphere(new THREE.Sphere());
      orbit.target.copy(sphere.center);
      var fov = camera.fov * Math.PI / 180;
      var fit = Math.min(fov, fov * camera.aspect);
      orbit.r = Math.max(10, sphere.radius / Math.sin(fit / 2));
      // tighten: fit the 8 box corners on screen (long thin parts would look tiny otherwise)
      var corners = [];
      for (var i = 0; i < 8; i++) {
        corners.push(new THREE.Vector3(i & 1 ? box.max.x : box.min.x, i & 2 ? box.max.y : box.min.y,
          i & 4 ? box.max.z : box.min.z));
      }
      for (var it = 0; it < 4; it++) {
        updateCamera();
        camera.updateMatrixWorld();
        var c = orbit.target.clone().project(camera);
        var mx = 0, my = 0;
        corners.forEach(function (k) {
          var p = k.clone().project(camera);
          mx = Math.max(mx, Math.abs(p.x - c.x));
          my = Math.max(my, Math.abs(p.y - c.y));
        });
        var allowX = Math.max(0.2, (1 - Math.abs(c.x)) * 0.88);
        var factor = Math.max(mx / allowX, my / 0.8);
        if (!isFinite(factor) || factor <= 0) break;
        orbit.r = Math.max(5, orbit.r * factor);
      }
    }
    function setView(name) {
      orbit.theta = VIEWS[name][0];
      orbit.phi = VIEWS[name][1];
      frame();
      updateCamera();
    }

    var pointers = {};
    var mode = null;
    var pinchStart = 0;
    var rStart = 0;
    function wireControls() {
      var c = renderer.domElement;
      c.addEventListener('contextmenu', function (e) { e.preventDefault(); });
      c.addEventListener('pointerdown', function (e) {
        c.setPointerCapture(e.pointerId);
        pointers[e.pointerId] = { x: e.clientX, y: e.clientY };
        var ids = Object.keys(pointers);
        if (ids.length === 2) {
          var a = pointers[ids[0]], b = pointers[ids[1]];
          pinchStart = Math.hypot(a.x - b.x, a.y - b.y) || 1;
          rStart = orbit.r;
          mode = 'pinch';
        } else {
          mode = (e.button === 2 || e.shiftKey) ? 'pan' : 'rotate';
        }
      });
      c.addEventListener('pointermove', function (e) {
        var p = pointers[e.pointerId];
        if (!p) return;
        var dx = e.clientX - p.x, dy = e.clientY - p.y;
        p.x = e.clientX; p.y = e.clientY;
        if (mode === 'rotate') {
          orbit.theta -= dx * 0.008;
          orbit.phi = Math.min(Math.PI - 0.001, Math.max(0.0001, orbit.phi - dy * 0.008));
        } else if (mode === 'pan') {
          var scale = 2 * orbit.r * Math.tan(camera.fov * Math.PI / 360) / c.clientHeight;
          var right = new THREE.Vector3().setFromMatrixColumn(camera.matrix, 0);
          var up = new THREE.Vector3().setFromMatrixColumn(camera.matrix, 1);
          orbit.target.addScaledVector(right, -dx * scale).addScaledVector(up, dy * scale);
        } else if (mode === 'pinch') {
          var ids = Object.keys(pointers);
          if (ids.length === 2) {
            var a = pointers[ids[0]], b = pointers[ids[1]];
            var d = Math.hypot(a.x - b.x, a.y - b.y) || 1;
            orbit.r = Math.max(1, rStart * pinchStart / d);
          }
        }
        updateCamera();
      });
      function up(e) { delete pointers[e.pointerId]; if (!Object.keys(pointers).length) mode = null; }
      c.addEventListener('pointerup', up);
      c.addEventListener('pointercancel', up);
      c.addEventListener('wheel', function (e) {
        e.preventDefault();
        orbit.r = Math.max(1, Math.min(40000, orbit.r * Math.exp(e.deltaY * 0.001)));
        updateCamera();
      }, { passive: false });

      document.querySelectorAll('[data-view]').forEach(function (b) {
        b.addEventListener('click', function () { setView(b.getAttribute('data-view')); });
      });
      document.getElementById('edges').addEventListener('change', function (e) { toggleEdges(e.target.checked); });
      document.getElementById('volume').addEventListener('change', function (e) {
        volume.visible = e.target.checked;
        requestRender();
      });
      document.getElementById('section').addEventListener('change', updateSection);
      document.getElementById('axis').addEventListener('change', updateSection);
      document.getElementById('cut').addEventListener('input', updateSection);
      document.getElementById('theme').addEventListener('click', function () {
        var next = isDark() ? 'light' : 'dark';
        document.documentElement.setAttribute('data-theme', next);
        storeTheme(next);
        applyTheme();
      });
      document.getElementById('parts').addEventListener('change', function (e) {
        var idx = Number(e.target.dataset.index);
        if (meshes[idx]) { meshes[idx].visible = e.target.checked; requestRender(); }
      });
      window.addEventListener('resize', resize);
      if (window.matchMedia) {
        var mq = window.matchMedia('(prefers-color-scheme: dark)');
        if (mq.addEventListener) mq.addEventListener('change', applyTheme);
      }
    }

    function toggleEdges(on) {
      edgeLines.forEach(function (l) { l.visible = on; });
      requestRender();
    }

    function updateSection() {
      var on = document.getElementById('section').checked;
      var axis = document.getElementById('axis').value;
      var t = Number(document.getElementById('cut').value) / 1000;
      var box = new THREE.Box3();
      meshes.forEach(function (m) { if (m) box.union(new THREE.Box3().setFromObject(m)); });
      var k = { x: 0, y: 1, z: 2 }[axis] || 0;
      var lo = box.min.getComponent(k), hi = box.max.getComponent(k);
      var pos = lo + (hi - lo) * t;
      var n = new THREE.Vector3(0, 0, 0);
      n.setComponent(k, -1);
      clipPlane.normal.copy(n);
      clipPlane.constant = pos;
      var planes = on ? [clipPlane] : [];
      meshes.forEach(function (m) {
        if (!m) return;
        m.material.clippingPlanes = planes;
        m.material.needsUpdate = true;
        m.children.forEach(function (ch) { ch.material.clippingPlanes = planes; ch.material.needsUpdate = true; });
      });
      var offset = partsGroup.position.getComponent(k);
      document.getElementById('cutpos').textContent = on
        ? 'Showing ' + axis.toUpperCase() + ' <= ' + fmt(pos - offset) + ' mm (part coordinates)'
        : '';
      requestRender();
    }

    function resize() {
      var w = stage.clientWidth || window.innerWidth;
      var h = stage.clientHeight || window.innerHeight;
      renderer.setSize(w, h);
      camera.aspect = w / h;
      // centre the part in the free area left of the panel on wide screens
      var panel = document.getElementById('panel');
      var shift = (!body.classList.contains('no-ui') && w > 700 && panel) ? (panel.offsetWidth + 24) / 2 : 0;
      if (shift) camera.setViewOffset(w, h, shift, 0, w, h); else camera.clearViewOffset();
      camera.updateProjectionMatrix();
      requestRender();
    }

    resize();
  }
})();
