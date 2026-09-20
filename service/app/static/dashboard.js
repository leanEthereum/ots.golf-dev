(function () {
  'use strict';
  document.querySelectorAll('figure.chart').forEach(function (figure) {
    var svg = figure.querySelector('svg.record-chart');
    var tip = figure.querySelector('.tooltip');
    var data = document.getElementById(figure.dataset.points || 'chart-points');
    if (!svg || !tip || !data) return;
    var points = JSON.parse(data.textContent);
    var cross = svg.querySelector('.crosshair');
    var plot = svg.closest('.chart-plot');
    function hideTip() { tip.hidden = true; cross.setAttribute('visibility', 'hidden'); }
    function showPoint(point) {
      cross.setAttribute('x1', point.x); cross.setAttribute('x2', point.x);
      cross.setAttribute('visibility', 'visible');
      tip.textContent = '';
      var head = document.createElement('strong');
      head.textContent = point.track + ' · ' + point.claim + ' ' + point.unit + (point.demo ? ' · demo' : '');
      tip.appendChild(head); tip.appendChild(document.createElement('br'));
      tip.appendChild(document.createTextNode(point.login + ' · ' + point.date));
      tip.hidden = false;
      var bounds = svg.getBoundingClientRect(), box = svg.viewBox.baseVal;
      var container = tip.parentElement.getBoundingClientRect();
      var x = bounds.left - container.left + point.x / box.width * bounds.width;
      var y = bounds.top - container.top + point.y / box.height * bounds.height;
      tip.style.left = Math.max(4, Math.min(x + 12, container.width - tip.offsetWidth - 8)) + 'px';
      tip.style.top = Math.max(4, y - tip.offsetHeight - 12) + 'px';
    }
    svg.addEventListener('pointermove', function (event) {
      if (!points.length || event.pointerType === 'touch') return;
      var p = svg.createSVGPoint(); p.x = event.clientX; p.y = event.clientY;
      var mouse = p.matrixTransform(svg.getScreenCTM().inverse()), best, distance = Infinity;
      points.forEach(function (point) {
        var d = Math.hypot(point.x - mouse.x, point.y - mouse.y);
        if (d < distance) { distance = d; best = point; }
      });
      if (distance < 45) showPoint(best); else hideTip();
    });
    svg.addEventListener('pointerleave', hideTip);
    plot.addEventListener('scroll', hideTip);
    window.addEventListener('resize', hideTip);
    document.addEventListener('keydown', function (event) { if (event.key === 'Escape') hideTip(); });
    svg.querySelectorAll('.chart-record').forEach(function (link) {
      link.addEventListener('focus', function () { showPoint(points[+link.dataset.point]); });
      link.addEventListener('blur', hideTip);
      link.addEventListener('pointerdown', function (event) {
        if (event.pointerType === 'touch') showPoint(points[+link.dataset.point]);
      });
    });
  });

  var chartButtons = document.querySelectorAll('.chart-btn');
  var chartPanels = document.querySelectorAll('.chart-panel');
  chartButtons.forEach(function (button) {
    button.addEventListener('click', function () {
      chartButtons.forEach(function (other) { other.setAttribute('aria-pressed', String(other === button)); });
      chartPanels.forEach(function (panel) { panel.hidden = panel.dataset.chart !== button.dataset.chart; });
    });
  });

  function fitRows() {
    document.querySelectorAll('.board-scroll[data-rows]').forEach(function (box) {
      var head = box.querySelector('thead'), row = box.querySelector('tbody tr');
      if (!head || !row || !row.offsetHeight) return;
      box.style.maxHeight = (head.offsetHeight + row.offsetHeight * Number(box.dataset.rows) + 2) + 'px';
    });
  }
  fitRows();
  window.addEventListener('resize', fitRows);
  document.addEventListener('click', function (event) {
    if (event.target.closest('.lower-btn, .upper-btn, .seg-btn')) window.requestAnimationFrame(fitRows);
  });

  var lowerButtons = document.querySelectorAll('.lower-btn');
  var lowerBoards = document.querySelectorAll('.framework-board[data-framework]');
  function showLower(framework) {
    var available = Array.prototype.some.call(lowerBoards, function (board) {
      return board.dataset.framework === framework;
    });
    if (!available && lowerBoards.length) framework = lowerBoards[0].dataset.framework;
    lowerButtons.forEach(function (button) { button.setAttribute('aria-pressed', String(button.dataset.framework === framework)); });
    lowerBoards.forEach(function (board) { board.hidden = board.dataset.framework !== framework; });
  }
  lowerButtons.forEach(function (button) {
    button.addEventListener('click', function () {
      showLower(button.dataset.framework);
      var url = new URL(location.href); url.searchParams.set('framework', button.dataset.framework);
      history.replaceState(null, '', url.pathname + url.search + url.hash);
    });
  });

  var upperButtons = document.querySelectorAll('.upper-btn');
  var upperBoards = document.querySelectorAll('.upper-board[data-upper]');
  function showUpper(track) {
    var available = Array.prototype.some.call(upperBoards, function (board) {
      return board.dataset.upper === track;
    });
    if (!available && upperBoards.length) track = upperBoards[0].dataset.upper;
    upperButtons.forEach(function (button) { button.setAttribute('aria-pressed', String(button.dataset.upper === track)); });
    upperBoards.forEach(function (board) { board.hidden = board.dataset.upper !== track; });
  }
  upperButtons.forEach(function (button) {
    button.addEventListener('click', function () {
      showUpper(button.dataset.upper);
      var url = new URL(location.href); url.searchParams.set('upper', button.dataset.upper);
      url.hash = 'upper';
      history.replaceState(null, '', url.pathname + url.search + url.hash);
    });
  });

  var buttons = document.querySelectorAll('.seg-btn');
  var panels = document.querySelectorAll('.board-track');
  function show(kind, updateUrl) {
    buttons.forEach(function (button) { button.setAttribute('aria-pressed', String(button.dataset.track === kind)); });
    panels.forEach(function (panel) { panel.hidden = panel.dataset.track !== kind; });
    document.querySelectorAll('.lower-only').forEach(function (element) { element.hidden = kind !== 'lower'; });
    document.querySelectorAll('.board-filters a').forEach(function (link) {
      var url = new URL(link.href); url.hash = 'lower'; link.href = url.href;
    });
    if (updateUrl) history.replaceState(null, '', location.pathname + location.search + '#' + kind);
  }
  buttons.forEach(function (button) { button.addEventListener('click', function () { show(button.dataset.track, true); }); });
  function fromUrl() {
    var params = new URL(location.href).searchParams;
    showLower(params.get('framework'));
    showUpper(params.get('upper'));
    show(location.hash === '#lower' ? 'lower' : 'upper', false);
    fitRows();
    if (location.hash === '#upper' || location.hash === '#lower') document.getElementById('board-title').scrollIntoView();
  }
  window.addEventListener('hashchange', fromUrl);
  window.addEventListener('popstate', fromUrl);
  fromUrl();

  document.querySelectorAll('.lb-table').forEach(function (table) {
    var body = table.querySelector('tbody');
    table.querySelectorAll('.sort-btn').forEach(function (button) {
      button.addEventListener('click', function () {
        var key = button.dataset.key, direction = button.dataset.dir;
        if (button.getAttribute('aria-pressed') === 'true') {
          direction = direction === 'asc' ? 'desc' : 'asc'; button.dataset.dir = direction;
        }
        table.querySelectorAll('.sort-btn').forEach(function (other) {
          other.setAttribute('aria-pressed', String(other === button));
          other.parentNode.setAttribute('aria-sort', other === button ? (direction === 'asc' ? 'ascending' : 'descending') : 'none');
        });
        var rows = Array.prototype.slice.call(body.querySelectorAll('tr.lb-row'));
        rows.sort(function (a, b) {
          var va = a.dataset[key], vb = b.dataset[key];
          if (va === '' && vb === '') return 0; if (va === '') return 1; if (vb === '') return -1;
          if (key !== 'date') { va = parseFloat(va); vb = parseFloat(vb); }
          return (va < vb ? -1 : va > vb ? 1 : 0) * (direction === 'asc' ? 1 : -1);
        });
        rows.forEach(function (row) { body.appendChild(row); });
      });
    });
  });
})();
