/* Aktien-Radar - statische PWA, liest data/quotes.json und data/news.json (per GitHub-Action aktualisiert) */
(function () {
'use strict';
var REPO = 'ayoub971-prog/aktien-radar';
var SECTOR_ORDER = ['Halbleiter/Hardware', 'Software/KI', 'Energie', 'Industrie/Luftfahrt', 'Finanzen', 'Rohstoffe/Gold', 'Konsum/Internet', 'Gesundheit', 'ETFs/Indizes', 'Sonstige'];
var TAGS = [
  { n: 'Quartalszahlen', re: /quartalszahl|quartalsergebnis|quartalsbericht|jahreszahlen|halbjahreszahlen|geschäftszahlen|\bearnings\b|quarterly results|\bq[1-4]\b.{0,12}(results|earnings|revenue)|(results|earnings) for (the )?(first|second|third|fourth)|\bumsatz\b|\bbilanz\b/i },
  { n: 'Gewinnwarnung', re: /gewinnwarnung|profit warning|senkt (die |seine |ihre )?(prognose|ziele)|cuts? (its )?(outlook|guidance|forecast)|lowers? (its )?(outlook|guidance)|warns? (of|on) (profit|earnings|sales)/i },
  { n: 'Übernahme', re: /übernahme|übernimmt|fusion|akquisition|\bacquires?\b|\bacquisition\b|\bmerger\b|\btakeover\b|\bbuyout\b|\bkauft\b.{0,30}(firma|unternehmen|startup)/i },
  { n: 'Klage', re: /\bklage\b|\bklagen\b|verklagt|\blawsuit\b|\bsues?\b|\bsued\b|kartell|antitrust|ermittlung|investigation|\bprobe\b|strafe|\bsettlement\b|\bsec charges\b/i },
  { n: 'Zoll', re: /\bzoll\b|\bzölle\b|\bzöllen\b|\btariffs?\b|handelskrieg|handelskonflikt|trade war|exportkontroll|export controls?|sanktion|sanctions?|embargo/i },
  { n: 'Zinsentscheid', re: /zinsentscheid|zinssenkung|zinserhöhung|leitzins|\bfed\b|\bfomc\b|\bsnb\b|\bezb\b|\becb\b|interest rates?|rate (cut|hike|decision)|powell|notenbank|nationalbank|federal reserve/i },
  { n: 'Rückruf', re: /rückruf|rückrufaktion|\brecalls?\b/i },
  { n: 'Prognose', re: /prognose|ausblick|\bguidance\b|\bforecast\b|\boutlook\b/i },
  { n: 'Upgrade/Downgrade', re: /\bupgrades?\b|\bdowngrades?\b|hochgestuft|abgestuft|heraufgestuft|herabgestuft|kaufempfehlung|kursziel|price target|\boutperform\b|\bunderperform\b|\boverweight\b|\bunderweight\b|analyst/i }
];
var NEW_GAP_MS = 30 * 60 * 1000;
var DAY = 86400000;

/* ---------- Hilfen ---------- */
function $(id) { return document.getElementById(id); }
function esc(s) { return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]; }); }
var errCount = 0;
function showErr(msg, kind) {
  try {
    var b = $('errBanner'); if (!b) return;
    if (errCount >= 4) return; errCount++;
    var d = document.createElement('div'); d.className = 'banner' + (kind === 'warn' ? '' : ' err'); d.textContent = msg; b.appendChild(d);
  } catch (e) {}
}
window.addEventListener('error', function (e) { showErr('Fehler: ' + (e && e.message ? e.message : 'unbekannt')); });
window.addEventListener('unhandledrejection', function (e) { showErr('Fehler: ' + (e && e.reason && e.reason.message ? e.reason.message : String(e && e.reason))); });

var store = {};
function lsGet(k) { try { var v = localStorage.getItem(k); return v === null ? (store[k] === undefined ? null : store[k]) : v; } catch (e) { return store[k] === undefined ? null : store[k]; } }
function lsSet(k, v) { store[k] = v; try { localStorage.setItem(k, v); } catch (e) {} }
function loadState() {
  var s = null; try { s = JSON.parse(lsGet('ar.state') || 'null'); } catch (e) {}
  if (!s || typeof s !== 'object') s = {};
  s.hidden = s.hidden instanceof Array ? s.hidden : []; s.custom = s.custom instanceof Array ? s.custom : [];
  s.order = s.order instanceof Array ? s.order : []; s.sec = s.sec && typeof s.sec === 'object' ? s.sec : {};
  s.sort = s.sort || 'eigene';
  // Alias: lokal per Kürzel hinzugefügtes BYD/BYDDY -> 1211.HK (Standardliste)
  var AL = { 'BYD': '1211.HK', 'BYDDY': '1211.HK', 'BYDDF': '1211.HK' };
  s.custom = s.custom.filter(function (c) { var t = AL[String(c.symbol).toUpperCase()] || (/^byd\b/i.test(c.name || '') && String(c.symbol).toUpperCase() !== '1211.HK' ? '1211.HK' : null); if (!t) return true; s.order = s.order.map(function (o) { return o === c.symbol ? t : o; }); return false; });
  s.order = s.order.filter(function (o, i) { return s.order.indexOf(o) === i; });
  return s;
}
var S = loadState();
function saveState() { lsSet('ar.state', JSON.stringify(S)); }

function fmtNum(x, d) {
  if (x == null || isNaN(x)) return '-';
  try { return new Intl.NumberFormat('de-CH', { minimumFractionDigits: d, maximumFractionDigits: d }).format(x); } catch (e) { return Number(x).toFixed(d); }
}
function fmtPrice(x) { return fmtNum(x, Math.abs(x) < 10 ? 3 : 2); }
function fmtSigned(x, d) { if (x == null || isNaN(x)) return '-'; return (x > 0 ? '+' : (x < 0 ? '-' : '')) + fmtNum(Math.abs(x), d); }
function ago(iso) {
  if (!iso) return 'unbekannt';
  var t = Date.parse(iso); if (isNaN(t)) return 'unbekannt';
  var m = Math.round((Date.now() - t) / 60000);
  if (m < 1) return 'gerade eben';
  if (m < 60) return 'vor ' + m + ' Min';
  var h = Math.round(m / 60); if (h < 24) return 'vor ' + h + ' Std';
  var d = Math.round(h / 24); if (d === 1) return 'gestern';
  return 'vor ' + d + ' Tagen';
}
function fmtD(iso) { var t = Date.parse(iso || ''); if (isNaN(t)) return '-'; try { return new Date(t).toLocaleDateString('de-CH', { weekday: 'short', day: '2-digit', month: '2-digit', year: 'numeric' }); } catch (e) { return iso.slice(0, 10); } }
function fmtDT(iso) {
  var t = Date.parse(iso || ''); if (isNaN(t)) return '-';
  try { return new Date(t).toLocaleString('de-CH', { weekday: 'short', day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' }); } catch (e) { return iso; }
}
function tagsFor(title) { var r = []; for (var i = 0; i < TAGS.length; i++) if (TAGS[i].re.test(title)) r.push(TAGS[i].n); return r; }

/* ---------- Daten ---------- */
var DEF = null, Q = null, N = null, CAT = null, dataErrors = [];
function getJSON(url) {
  return fetch(url, { cache: 'no-cache' }).then(function (r) {
    if (!r.ok) throw new Error(url + ' (HTTP ' + r.status + ')');
    return r.json();
  });
}
function loadData() {
  var jobs = [
    getJSON('watchlist.json').then(function (d) { DEF = d; lsSet('ar.cache.wl', JSON.stringify(d)); }),
    getJSON('data/quotes.json').then(function (d) { Q = d; lsSet('ar.cache.q', JSON.stringify(d)); }),
    getJSON('data/news.json').then(function (d) { N = d; try { localStorage.setItem('ar.cache.n', JSON.stringify(d)); } catch (e) {} })
  ];
  var ij = getJSON('data/insights.json').then(function (d) { I = d; try { localStorage.setItem('ar.cache.i', JSON.stringify(d)); } catch (e) {} },
    function () { if (!I) { try { I = JSON.parse(localStorage.getItem('ar.cache.i') || 'null'); } catch (e) {} } });
  jobs.push(ij.then(function () {}, function () {}));
  var aj = getJSON('data/ai.json').then(function (d) { AI = d; try { localStorage.setItem('ar.cache.ai', JSON.stringify(d)); } catch (e) {} },
    function () { if (!AI) { try { AI = JSON.parse(localStorage.getItem('ar.cache.ai') || 'null'); } catch (e) {} } });
  jobs.push(aj.then(function () {}, function () {}));
  // Per Kurzbefehl hinzugefügte Aktien automatisch einblenden (auch wenn früher entfernt)
  jobs.push(getJSON('data/added.json').then(function (d) {
    var it = (d && d.items) || [], last = S.addSeen || 0, mx = last, ch = false;
    for (var i = 0; i < it.length; i++) {
      if (!(it[i].at > last)) continue; mx = Math.max(mx, it[i].at);
      var hi = S.hidden.indexOf(it[i].symbol); if (hi >= 0) { S.hidden.splice(hi, 1); ch = true; }
      if (S.order.length && S.order.indexOf(it[i].symbol) < 0) { S.order.push(it[i].symbol); ch = true; }
    }
    if (mx !== last || ch) { S.addSeen = mx; saveState(); }
  }, function () {}));
  jobs.push(getJSON('data/audio/index.json').then(function (d) { AUD = d; }, function () {}));
  jobs.push(podLoad());
  return Promise.all(jobs.map(function (j, i) { return j.then(function () { return null; }, function (e) { return { i: i, e: e }; }); })).then(function (res) {
    dataErrors = []; disTitles = null;
    var keys = ['ar.cache.wl', 'ar.cache.q', 'ar.cache.n'];
    for (var k = 0; k < res.length; k++) {
      if (res[k]) {
        var cached = null; try { cached = JSON.parse(lsGet(keys[res[k].i]) || 'null'); } catch (e) {}
        if (cached) { if (res[k].i === 0) DEF = DEF || cached; if (res[k].i === 1) Q = Q || cached; if (res[k].i === 2) N = N || cached; }
        dataErrors.push((cached ? 'Zeige zuletzt gespeicherte Daten. ' : 'Keine Daten. ') + 'Grund: ' + res[k].e.message);
      }
    }
    if (!DEF) DEF = { sectors: SECTOR_ORDER, stocks: [], market_topics: [] };
    if (!Q) Q = { quotes: {}, generated_at: null };
    if (!N) N = { items: [], generated_at: null };
    prepNews();
  });
}
var byId = {}, I = null, AI = null;
function prepNews() {
  var it = N.items || [];
  for (var i = 0; i < it.length; i++) { it[i]._t = Date.parse(it[i].published) || 0; it[i]._tags = tagsFor(it[i].title + ' ' + (it[i].title_de || '')); }
  it.sort(function (a, b) { return b._t - a._t; });
}

/* ---------- Watchlist (Standard + lokal) ---------- */
function stockList() {
  var out = [], seen = {}, i;
  var defs = (DEF && DEF.stocks) || [];
  for (i = 0; i < defs.length; i++) {
    var d = defs[i];
    if (S.hidden.indexOf(d.symbol) >= 0) continue;
    out.push({ symbol: d.symbol, name: d.name, sector: S.sec[d.symbol] || d.sector || 'Sonstige', custom: false }); seen[d.symbol] = 1;
  }
  for (i = 0; i < S.custom.length; i++) {
    var c = S.custom[i]; if (seen[c.symbol]) continue;
    out.push({ symbol: c.symbol, name: c.name || c.symbol, sector: S.sec[c.symbol] || c.sector || 'Sonstige', custom: true }); seen[c.symbol] = 1;
  }
  return out;
}
function orderedList() {
  var l = stockList(), pos = {}, i;
  for (i = 0; i < S.order.length; i++) pos[S.order[i]] = i;
  var base = {}; for (i = 0; i < l.length; i++) base[l[i].symbol] = i;
  l.sort(function (a, b) {
    var pa = pos[a.symbol] === undefined ? 100000 + base[a.symbol] : pos[a.symbol];
    var pb = pos[b.symbol] === undefined ? 100000 + base[b.symbol] : pos[b.symbol];
    return pa - pb;
  });
  return l;
}
function quoteOf(sym) { return Q && Q.quotes ? Q.quotes[sym] : null; }

/* ---------- Neu-Markierung ---------- */
var baseline = 0;
function initBaseline() {
  var now = Date.now(), last = parseInt(lsGet('ar.last') || '0', 10), base = parseInt(lsGet('ar.base') || '0', 10);
  if (!last || !base) base = now;                      // erster Besuch: nichts als neu markieren
  else if (now - last > NEW_GAP_MS) base = last;       // neuer Besuch: alles seit dem letzten Besuch ist neu
  lsSet('ar.base', String(base)); lsSet('ar.last', String(now)); baseline = base;
}
function touchLast() { lsSet('ar.last', String(Date.now())); }
function isNew(it) { return it._t > baseline; }
function newCount(sym) {
  var it = N.items || [], c = 0;
  for (var i = 0; i < it.length; i++) { if (it[i]._t <= baseline) break; if (it[i].symbols && it[i].symbols.indexOf(sym) >= 0) c++; }
  return c;
}

/* ---------- Darstellung ---------- */
function sparkSvg(q, w, h) {
  var pts = q && q.spark_day && q.spark_day.length >= 8 ? q.spark_day : (q && q.spark_5d && q.spark_5d.length >= 2 ? q.spark_5d : null);
  var up = q && q.change != null ? q.change >= 0 : true, col = up ? '#38c172' : '#ef5350';
  if (!pts) return '<svg class="spark" viewBox="0 0 100 32" aria-hidden="true"></svg>';
  var day = pts === q.spark_day, mn = Math.min.apply(null, pts), mx = Math.max.apply(null, pts);
  if (day && q.prev_close != null) { mn = Math.min(mn, q.prev_close); mx = Math.max(mx, q.prev_close); }
  var rg = mx - mn || 1, d = [], i;
  for (i = 0; i < pts.length; i++) d.push((i / (pts.length - 1) * 100).toFixed(1) + ',' + (30 - (pts[i] - mn) / rg * 28).toFixed(1));
  var base = day && q.prev_close != null ? '<line x1="0" x2="100" y1="' + (30 - (q.prev_close - mn) / rg * 28).toFixed(1) + '" y2="' + (30 - (q.prev_close - mn) / rg * 28).toFixed(1) + '" stroke="#6b7076" stroke-width="1" stroke-dasharray="3 3" vector-effect="non-scaling-stroke"/>' : '';
  return '<svg class="spark" viewBox="0 0 100 32" preserveAspectRatio="none" aria-hidden="true">' + base + '<polyline fill="none" stroke="' + col + '" stroke-width="1.8" vector-effect="non-scaling-stroke" stroke-linejoin="round" points="' + d.join(' ') + '"/></svg>';
}
function chgPill(q) {
  if (!q || q.change_pct == null) return '<span class="chg flat">-</span>';
  var cls = q.change_pct > 0.005 ? 'up' : (q.change_pct < -0.005 ? 'down' : 'flat');
  return '<span class="chg ' + cls + '">' + fmtSigned(q.change_pct, 2) + ' %</span>';
}
var MV_UP = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><polyline points="5,15 12,8 19,15"/></svg>';
var MV_DN = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><polyline points="5,9 12,16 19,9"/></svg>';

function rowHtml(s, showMove) {
  var q = quoteOf(s.symbol), nn = newCount(s.symbol);
  var right, sub;
  if (q) {
    right = '<div class="p">' + fmtPrice(q.price) + '</div>' + chgPill(q);
    sub = '<span>' + (q.currency || '') + ' ' + fmtSigned(q.change, Math.abs(q.price) < 10 ? 3 : 2) + '</span><span>Kurs ' + esc(ago(q.market_time)) + '</span>' + (q.stale ? '<span class="pill warn">Kurs veraltet</span>' : '') + (nn ? '<span class="new">' + nn + ' neu</span>' : '');
  } else {
    right = '<span class="pill warn">wartet</span>';
    sub = '<span>Daten werden beim nächsten Update geladen (siehe Liste)</span>';
  }
  var mv = showMove ? '<div class="mv"><button class="small" data-mv="up" data-s="' + esc(s.symbol) + '" aria-label="Nach oben">' + MV_UP + '</button><button class="small" data-mv="down" data-s="' + esc(s.symbol) + '" aria-label="Nach unten">' + MV_DN + '</button></div>' : '';
  return '<a class="row" href="#/s/' + encodeURIComponent(s.symbol) + '"><div class="l"><b>' + esc(s.symbol) + '</b><span>' + esc(s.name) + '</span></div>' + (q ? sparkSvg(q) : '<div></div>') + '<div class="r" style="display:flex;align-items:center;justify-content:flex-end"><div>' + right + '</div>' + mv + '</div><div class="sub">' + sub + '</div></a>';
}

function statusLine() {
  var qa = Q && Q.generated_at, na = N && N.generated_at;
  var old = qa && (Date.now() - Date.parse(qa) > 3 * 3600 * 1000);
  var h = '<p class="tiny">Kurse: Stand ' + esc(ago(qa)) + ' | Nachrichten: Stand ' + esc(ago(na)) + ' | Quelle Yahoo Finance, ggf. 15 Min verzögert</p>';
  if (old) h += '<div class="banner">Die Daten sind älter als 3 Stunden. Die automatische Aktualisierung auf GitHub hat sich verspätet (kommt vor) oder ist ausgefallen. Es wird der letzte bekannte Stand gezeigt.</div>';
  for (var i = 0; i < dataErrors.length; i++) h += '<div class="banner err">' + esc(dataErrors[i]) + '</div>';
  if (Q && Q.errors && Q.errors.length) h += '<div class="banner">Beim letzten Update ohne Kurs: ' + esc(Q.errors.map(function (e) { return e.symbol; }).join(', ')) + '</div>';
  return h;
}

function viewHome() {
  var list = stockList(), h = podHtml();
  h += '<div class="bar"><select id="sortSel" aria-label="Sortierung">' +
    '<option value="eigene">Eigene Reihenfolge</option><option value="az">Name A-Z</option><option value="sektor">Nach Sektor</option><option value="tag">Tagesveränderung</option></select>' +
    '<button id="reloadBtn" class="small">Aktualisieren</button></div>';
  h += '<div class="srch"><input type="search" id="hq" placeholder="Aktie suchen…" autocomplete="off" autocapitalize="none" autocorrect="off" spellcheck="false"><button id="hqX" type="button" aria-label="Suche löschen" hidden>×</button></div>';
  h += statusLine();
  var mode = S.sort, i;
  if (!list.length) h += '<p class="muted">Die Liste ist leer. Unter "Liste" kannst du Aktien hinzufügen.</p>';
  if (mode === 'az') {
    list.sort(function (a, b) { return a.name.toLowerCase() < b.name.toLowerCase() ? -1 : 1; });
    for (i = 0; i < list.length; i++) h += rowHtml(list[i], false);
  } else if (mode === 'tag') {
    list.sort(function (a, b) {
      var qa = quoteOf(a.symbol), qb = quoteOf(b.symbol);
      var pa = qa && qa.change_pct != null ? qa.change_pct : -1e9, pb = qb && qb.change_pct != null ? qb.change_pct : -1e9;
      return pb - pa;
    });
    for (i = 0; i < list.length; i++) h += rowHtml(list[i], false);
  } else if (mode === 'sektor') {
    var groups = {}, order = SECTOR_ORDER.slice();
    for (i = 0; i < list.length; i++) { var sc = list[i].sector; if (order.indexOf(sc) < 0) order.push(sc); (groups[sc] = groups[sc] || []).push(list[i]); }
    for (var g = 0; g < order.length; g++) {
      var gl = groups[order[g]]; if (!gl) continue;
      gl.sort(function (a, b) { return a.name.toLowerCase() < b.name.toLowerCase() ? -1 : 1; });
      h += '<div class="sector">' + esc(order[g]) + '</div>';
      for (i = 0; i < gl.length; i++) h += rowHtml(gl[i], false);
    }
  } else {
    list = orderedList();
    for (i = 0; i < list.length; i++) h += rowHtml(list[i], true);
    h += '<p class="tiny">Mit den Pfeilen rechts änderst du die Reihenfolge.</p>';
  }
  $('view').innerHTML = h;
  $('sortSel').value = mode;
  $('sortSel').onchange = function () { S.sort = $('sortSel').value; saveState(); route(); };
  $('reloadBtn').onclick = function () { reload(true); };
  var hq = $('hq');
  try { hq.value = sessionStorage.getItem('ar_q') || ''; } catch (e) {}
  hq.oninput = function () { try { sessionStorage.setItem('ar_q', hq.value); } catch (e) {} homeFilter(); };
  $('hqX').onclick = function () { hq.value = ''; hq.oninput(); hq.focus(); };
  homeFilter();
  bindPod();
}
function homeFilter() {
  var hq = $('hq'); if (!hq) return;
  var q = hq.value.trim().toLowerCase(), rows = document.querySelectorAll('#view a.row'), n = 0, i;
  $('hqX').hidden = !q;
  for (i = 0; i < rows.length; i++) {
    var b = rows[i].querySelector('.l b'), sp = rows[i].querySelector('.l span');
    var t = ((b ? b.textContent : '') + ' ' + (sp ? sp.textContent : '')).toLowerCase();
    var ok = !q || t.indexOf(q) >= 0; rows[i].style.display = ok ? '' : 'none'; if (ok) n++;
  }
  var secs = document.querySelectorAll('#view .sector');
  for (i = 0; i < secs.length; i++) { var e = secs[i].nextElementSibling, any = false; while (e && e.classList.contains('row')) { if (e.style.display !== 'none') any = true; e = e.nextElementSibling; } secs[i].style.display = any ? '' : 'none'; }
  var m = $('hqNone');
  if (q && !n) { if (!m) { m = document.createElement('p'); m.id = 'hqNone'; m.className = 'muted'; hq.parentNode.parentNode.insertBefore(m, hq.parentNode.nextSibling); } m.textContent = 'Keine Aktie gefunden für «' + hq.value.trim() + '».'; }
  else if (m) m.parentNode.removeChild(m);
}

function offBadge(it) { return it.official ? '<span class="offb">Offiziell' + (it.official === 'sec' ? ' · SEC' : '') + '</span>' : ''; }
function origLine(it) { return it.title_de && it.title_de !== it.title ? '<div class="orig">' + esc(it.title) + '</div>' : ''; }
function newsHtml(it, showSyms) {
  var h = '<div class="news' + (it.official ? ' off' : '') + '"><div class="m">' + offBadge(it) + (isNew(it) ? '<span class="new">Neu</span>' : '') + '<span>' + esc(it.source) + '</span><span>' + esc(ago(it.published)) + '</span>' + (disputed(it) ? '<span class="dis">Die Quellen sind sich uneinig</span>' : '');
  if (showSyms && it.symbols) for (var s = 0; s < it.symbols.length && s < 3; s++) h += '<span class="sym">' + esc(it.symbols[s]) + '</span>';
  h += '</div><a class="t" href="' + esc(it.link) + '" target="_blank" rel="noopener noreferrer">' + esc(it.title_de || it.title) + '</a>' + origLine(it) + (srcDesc(it.source, it.official) ? '<div class="sdesc">' + esc(it.source) + ': ' + esc(srcDesc(it.source, it.official)) + '</div>' : '') + '<div class="m">';
  for (var t = 0; t < it._tags.length; t++) h += '<span class="tag">' + esc(it._tags[t]) + '</span>';
  return h + '</div></div>';
}

function viewDetail(sym) {
  var l = stockList(), s = null, i;
  for (i = 0; i < l.length; i++) if (l[i].symbol === sym) s = l[i];
  if (!s) { var defs = (DEF && DEF.stocks) || []; for (i = 0; i < defs.length; i++) if (defs[i].symbol === sym) s = { symbol: sym, name: defs[i].name }; }
  if (!s) { $('view').innerHTML = '<a class="back" href="#/">Zurück</a><p class="muted">Aktie nicht gefunden.</p>'; return; }
  var q = quoteOf(sym), h = '<a class="back" href="' + backHash() + '">Zurück zur Liste</a><h2 style="margin-top:4px">' + esc(s.name) + '</h2><div class="muted">' + esc(sym) + (q && q.exchange ? ' - ' + esc(q.exchange) : '') + '</div>';
  if (q) {
    h += '<div class="big">' + fmtPrice(q.price) + ' <span style="font-size:18px" class="muted">' + esc(q.currency || '') + '</span></div>';
    h += '<div style="margin:6px 0">' + chgPill(q) + ' <span class="muted">' + fmtSigned(q.change, Math.abs(q.price) < 10 ? 3 : 2) + '</span></div>';
    h += aiHtml(sym, s);
    h += askHtml(s);
    h += '<div class="card" style="padding:8px"><svg viewBox="0 0 100 32" preserveAspectRatio="none" style="width:100%;height:110px;display:block">' + sparkSvg(q).replace(/^<svg[^>]*>/, '').replace(/<\/svg>$/, '') + '</svg><div class="tiny" style="padding:4px 6px">' + (q.spark_day && q.spark_day.length >= 8 ? 'Verlauf des letzten Handelstags (gestrichelt: Vortagesschluss)' : 'Verlauf der letzten 5 Handelstage') + '</div></div>';
    h += '<div class="kv"><div><span>Vortagesschluss</span>' + fmtPrice(q.prev_close) + '</div><div><span>Letzter Kurs</span>' + esc(fmtDT(q.market_time)) + '</div><div><span>52 Wochen Hoch</span>' + fmtPrice(q.high52) + '</div><div><span>52 Wochen Tief</span>' + fmtPrice(q.low52) + '</div><div><span>Daten geholt</span>' + esc(ago(q.fetched_at)) + '</div><div><span>Sektor</span>' + esc(s.sector || '-') + '</div></div>';
    if (q.stale) h += '<div class="banner">Kurs konnte beim letzten Update nicht geholt werden: ' + esc(q.error || '') + '</div>';
  } else h += aiHtml(sym, s) + '<div class="banner">Für diese Aktie gibt es noch keine Kurse und Nachrichten. Tippe auf den Knopf, dann auf GitHub unten auf "Create" bzw. "Submit new issue". Nach etwa 2 bis 5 Minuten sind die Daten da (dann oben "Aktualisieren"). Du kannst auch einfach Mika schreiben.<br><a class="pill" target="_blank" rel="noopener noreferrer" style="display:inline-block;margin-top:10px;padding:10px 16px;color:var(--text)" href="' + reqLink([{ symbol: s.symbol, name: s.name, sector: s.sector }]) + '">Daten für ' + esc(s.symbol) + ' anfordern</a></div>';
  h += insightsHtml(sym, q);
  h += '<p style="margin:10px 0"><button id="dReload">Aktualisieren</button> <a class="pill" href="https://finance.yahoo.com/quote/' + encodeURIComponent(sym) + '" target="_blank" rel="noopener noreferrer">Auf Yahoo Finance öffnen</a></p>';
  var items = (N.items || []).filter(function (x) { return x.symbols && x.symbols.indexOf(sym) >= 0; });
  var wk = Date.now() - 7 * DAY;   // offizielle Meldungen der letzten 7 Tage zuerst, sonst neueste zuerst
  items = items.filter(function (x) { return x.official && x._t >= wk; }).concat(items.filter(function (x) { return !(x.official && x._t >= wk); }));
  var nn = items.filter(isNew).length;
  h += '<h2>Meldungen (' + items.length + (nn ? ', ' + nn + ' neu' : '') + ')</h2><p class="tiny">Offizielle Mitteilungen der letzten 7 Tage oben, sonst neueste zuerst. Zuordnung per Suchbegriff (Firmenname), nicht jede Meldung betrifft die Aktie direkt.</p>';
  if (!items.length) h += '<p class="muted">Keine Meldungen gefunden.</p>';
  var shown = 0; for (i = 0; i < items.length; i++) { if (items[i].official || shown < 60) { h += newsHtml(items[i], false); if (!items[i].official) shown++; } }
  h += '<a class="back backBottom" href="' + backHash() + '">← Zurück zur Liste</a>';
  h += '<div style="height:70px"></div><a class="backFloat" href="' + backHash() + '">← Zurück zur Liste</a>';
  $('view').innerHTML = h;
  if ($('dReload')) $('dReload').onclick = function () { reload(true); };
  bindPlayer(sym);
  bindAsk(s);
  window.scrollTo(0, 0);
}
/* ---------- KI-Zusammenfassung (journalistisch) + Vorlesen ---------- */
var SRC_JS = { 'reuters': 'internationale Nachrichtenagentur', 'bloomberg': 'US-Finanznachrichtendienst', "barron's": 'US-Finanzmagazin', 'yahoo': 'Finanzportal, bündelt Meldungen verschiedener Anbieter', 'cnbc': 'US-Wirtschaftssender', 'finanzen.net': 'deutsches Finanzportal', 'finanzen.ch': 'Schweizer Finanzportal' };
function srcMap() { return (AI && AI.sources) || SRC_JS; }
function srcDesc(src, official) {
  if (official === 'sec') return 'Pflichtmeldung bei der US-Börsenaufsicht SEC';
  if (official) return 'Mitteilung der Firma selbst';
  var m = srcMap(), s = String(src || '').toLowerCase(), ks = Object.keys(m).sort(function (a, b) { return b.length - a.length; });
  for (var i = 0; i < ks.length; i++) if (s.indexOf(ks[i]) >= 0) return m[ks[i]];
  return '';
}
function aiOf(sym) { return AI && AI.stocks ? AI.stocks[sym] : null; }
var disTitles = null;
function disputed(it) {
  if (!disTitles) { disTitles = {}; var st = (AI && AI.stocks) || {};
    for (var k in st) { var w = st[k].widersprueche || []; for (var i = 0; i < w.length; i++) for (var j = 0; j < w[i].seiten.length; j++) if (w[i].seiten[j].titel) disTitles[w[i].seiten[j].titel] = 1; } }
  return !!disTitles[it.title];
}
function srcSpan(e) {
  if (!e.quelle) return '';
  var d = e.desc || srcDesc(e.quelle);
  return ' <span class="src">' + esc(e.quelle) + (d && d.toLowerCase().indexOf(e.quelle.toLowerCase()) < 0 ? ', ' + esc(d) : (d ? '' : '')) + '</span>';
}
function stmtList(arr, cls) {
  var h = '<ul class="sumb ' + (cls || '') + '">';
  for (var i = 0; i < arr.length; i++) h += '<li>' + (arr[i].rechtlich ? '<span class="law">Rechtliches</span> ' : '') + esc(arr[i].text) + srcSpan(arr[i]) + '</li>';
  return h + '</ul>';
}
function fallbackSpeech(sym, s) {
  var x = I && I.stocks ? I.stocks[sym] : null, t = (s && s.name ? s.name + '. ' : '');
  if (x && x.summary) {
    t += x.summary.text.join(' ').replace(/×/g, ' mal').replace(/Ø/g, 'durchschnittliches').replace(/%/g, 'Prozent').replace(/Std\./g, 'Stunden') + ' ';
    var b = x.summary.bullets || [];
    for (var i = 0; i < b.length && i < 4; i++) { var d = srcDesc(b[i].source, b[i].official); t += (b[i].official ? 'Mitteilung der Firma: ' : 'Laut ' + b[i].source + (d ? ', ' + d : '') + ': ') + (b[i].title_de || b[i].title).replace(/[.!?]*$/, '.') + ' '; }
  } else t += 'Noch keine Zusammenfassung vorhanden. ';
  return t + 'Keine Anlageberatung.';
}
function speechFor(sym, s) {
  var a = aiOf(sym);
  if (a && a.vorlesetext) return { text: a.vorlesetext, id: a.id || a.generated_at, ai: true };
  var t = fallbackSpeech(sym, s); return { text: t, id: 'x' + hashStr(t), ai: false };
}
function hashStr(t) { var h = 0; for (var i = 0; i < t.length; i++) h = (h * 31 + t.charCodeAt(i)) | 0; return (h >>> 0).toString(36); }
function aiHtml(sym, s) {
  var a = aiOf(sym), h = '<div class="card ai"><h3 style="margin-top:0">Zusammenfassung der Quellen</h3>';
  h += '<div class="player" id="pl"><button id="plPlay" class="primary">▶ Vorlesen</button><button id="plPause" hidden>❚❚ Pause</button><button id="plStop" hidden>■ Stop</button><span id="plNew" class="new" hidden>Neu</span><span id="plInfo" class="tiny"></span></div>';
  h += '<a class="backTop" href="' + backHash() + '">← Zurück zur Aktie in der Liste</a>';
  h += '<button type="button" id="askJump" style="display:block;width:100%;margin:8px 0 4px">🤖 KI fragen</button>';
  if (!a) {
    h += '<p class="tiny">Die KI-Zusammenfassung ist für diese Aktie noch nicht erstellt. Vorgelesen wird die einfache Zusammenfassung aus den Schlagzeilen.</p></div>';
    return h;
  }
  h += '<div class="risk"><h3>Risiken und Negatives</h3>' + (a.risiken && a.risiken.length ? stmtList(a.risiken) : '<p class="sumt">In den vorliegenden Meldungen nichts gefunden.</p>') + '</div>';
  h += '<h3>Kurzüberblick</h3>' + stmtList(a.kurzueberblick || []);
  if (a.widersprueche && a.widersprueche.length) {
    h += '<h3>Widersprüche zwischen Quellen</h3>';
    for (var i = 0; i < a.widersprueche.length; i++) { var w = a.widersprueche[i];
      h += '<div class="wid"><span class="dis">Die Quellen sind sich uneinig</span> <b>' + esc(w.thema) + '</b>' + stmtList(w.seiten.map(function (x) { return { text: x.text, quelle: x.quelle, desc: x.desc }; })) + '</div>'; }
  } else h += '<h3>Widersprüche zwischen Quellen</h3><p class="sumt">Keine Widersprüche in den vorliegenden Meldungen.</p>';
  if (a.analysten && a.analysten.length && !(a.bewertungen && a.bewertungen.length)) h += '<h3>Analysten</h3>' + stmtList(a.analysten);
  if (a.bewertungen && a.bewertungen.length) {
    h += '<h3>Analysten-Bewertungen</h3>';
    for (var bi = 0; bi < a.bewertungen.length; bi++) { var b = a.bewertungen[bi];
      h += '<div class="bew"><div><b>' + esc(b.firma || 'Analyst') + '</b>' + (b.datum ? ' <span class="tiny">' + esc(String(b.datum).replace(/^(\d{4})-(\d\d)-(\d\d)$/, '$3.$2.$1')) + '</span>' : '') + '</div>' +
        '<div>' + (b.rating ? '<span class="rat">' + esc(b.rating) + '</span>' : '') + (b.kursziel ? ' Kursziel <b>' + esc(b.kursziel) + '</b>' : '') + '</div>' +
        (b.warum ? '<div class="sumt">' + esc(b.warum) + '</div>' : '') + '<div>' + srcSpan(b) + '</div></div>'; }
  }
  var fa = a.firma_aktuell || {};
  if ((fa.aufwertend && fa.aufwertend.length) || (fa.abwertend && fa.abwertend.length)) {
    h += '<h3>Was die Firma gerade macht</h3>';
    if (fa.aufwertend && fa.aufwertend.length) h += '<div class="auf"><b>▲ Wertet auf</b>' + stmtList(fa.aufwertend) + '</div>';
    if (fa.abwertend && fa.abwertend.length) h += '<div class="ab"><b>▼ Wertet ab</b>' + stmtList(fa.abwertend) + '</div>';
  }
  if (a.kennzahlen && a.kennzahlen.length) {
    h += '<h3>Kennzahlen kurz erklärt</h3>';
    for (var ki = 0; ki < a.kennzahlen.length; ki++) { var k = a.kennzahlen[ki];
      h += '<div class="kz' + (k.wichtig ? ' wichtig' : '') + '"><div>' + (k.wichtig ? '🚨 ' : '') + '<b>' + esc(k.name) + '</b>' + (k.wert ? ': ' + esc(k.wert) : '') + '</div>' +
        (k.grund ? '<div class="sumt">' + esc(k.grund) + '</div>' : '') + (k.erklaerung ? '<div class="tiny">Erklärt: ' + esc(k.erklaerung) + '</div>' : '') + '<div>' + srcSpan(k) + '</div></div>'; }
  }
  h += '<p class="tiny">Von einer KI (Google Gemini) neutral aus ' + (a.n_meldungen || 'den') + ' Schlagzeilen und den Analystendaten zusammengefasst, Stand ' + esc(ago(a.generated_at)) + '. Nur Schlagzeilen ausgewertet, Fehler möglich. Keine Anlageberatung.</p></div>';
  return h;
}
/* Player: Satzweise (iOS pausiert/fortsetzt speechSynthesis unzuverlässig). Position pro Aktie in localStorage. */
var P = { sym: null, sents: [], idx: 0, playing: false, id: null, tok: 0 };
var AUD = null, AEL = null;   // Gemini-Stimme: data/audio/index.json + ein <audio>-Element
function audioFor(sym, sp) {
  var e = AUD && AUD.stocks && AUD.stocks[sym];
  return (sp.ai && e && e.file && e.id && e.id === sp.id) ? e : null;   // nur wenn zur aktuellen Zusammenfassung passend
}
function aEl() { if (!AEL) { AEL = new Audio(); AEL.preload = 'none'; } return AEL; }
function fmtT(s) { s = Math.max(0, Math.floor(s || 0)); return Math.floor(s / 60) + ':' + ('0' + s % 60).slice(-2); }
function splitSents(t) { return (t.match(/[^.!?]+(?:[.!?]+(?=\s|$)|$)/g) || [t]).map(function (x) { return x.trim(); }).filter(function (x) { return x.length > 1; }); }
function posGet(sym) { try { return JSON.parse(lsGet('ar.tts.' + sym) || 'null'); } catch (e) { return null; } }
function posSet(sym, o) { lsSet('ar.tts.' + sym, JSON.stringify(o)); }
function pickVoice() {
  var ss = window.speechSynthesis; if (!ss) return null;
  var v = ss.getVoices().filter(function (x) { return /^de/i.test(x.lang); });
  var good = function (x) { return /premium|enhanced|erweitert|neural|natural/i.test(x.name + ' ' + (x.voiceURI || '')); };
  var hq = v.filter(good); if (hq.length) v = hq.concat(v.filter(function (x) { return !good(x); }));
  var fem = ['anna', 'petra', 'helena', 'marlene', 'vicki', 'katja', 'seraphina', 'leni', 'sandy', 'shelley', 'flo', 'google deutsch'];
  for (var f = 0; f < fem.length; f++) for (var i = 0; i < v.length; i++) if (v[i].name.toLowerCase().indexOf(fem[f]) >= 0 && /ch/i.test(v[i].lang)) return v[i];
  for (f = 0; f < fem.length; f++) for (i = 0; i < v.length; i++) if (v[i].name.toLowerCase().indexOf(fem[f]) >= 0) return v[i];
  return v[0] || null;
}
function plUI() {
  if (!$('pl')) return;
  var st = posGet(P.sym) || {}, resumable = !P.playing && P.idx > 0 && P.idx < P.sents.length;
  if (P.audio) resumable = !P.playing && P.t > 0;
  $('plPlay').textContent = P.playing ? '▶ Läuft' : (resumable ? '▶ Weiter' : '▶ Vorlesen');
  $('plPlay').disabled = P.playing;
  $('plPause').hidden = !P.playing; $('plStop').hidden = !(P.playing || resumable); $('plStop').textContent = P.playing ? '■ Stop' : '↺ Von vorn';
  $('plNew').hidden = !!st.heard;
  if (P.audio) { $('plInfo').textContent = 'Gemini-Stimme' + (P.playing || resumable ? ' · ' + fmtT(P.t) + (P.audio.dur ? ' / ' + fmtT(P.audio.dur) : '') : ''); return; }
  $('plInfo').textContent = !window.speechSynthesis ? 'Vorlesen wird von diesem Browser nicht unterstützt.' : (P.playing || resumable ? 'Satz ' + Math.min(P.idx + 1, P.sents.length) + ' von ' + P.sents.length : '');
}
function plSave() { var st = posGet(P.sym) || {}; posSet(P.sym, { id: P.id, idx: P.idx, t: P.t || 0, heard: !!st.heard }); }
function plAudioPlay() {
  var a = aEl(), src = 'data/audio/' + encodeURIComponent(P.audio.file) + '?v=' + P.audio.hash, tok = ++P.tok, last = 0;
  if (a.dataset.src !== src) { a.src = src; a.dataset.src = src; }
  var seek = function () { try { if (Math.abs(a.currentTime - P.t) > 1) a.currentTime = P.t; } catch (e) {} };
  a.onloadedmetadata = seek;
  a.ontimeupdate = function () { if (tok !== P.tok) return; P.t = a.currentTime; if (P.t - last > 2 || P.t < last) { last = P.t; plSave(); plUI(); } };
  a.onended = function () { if (tok !== P.tok) return; P.playing = false; P.t = 0; posSet(P.sym, { id: P.id, idx: 0, t: 0, heard: true }); plUI(); };
  a.onerror = function () { if (tok !== P.tok) return; P.audio = null; P.playing = true; plSpeak(); };   // Datei fehlt: Geraetestimme
  seek();
  var pr = a.play(); if (pr && pr.catch) pr.catch(function () { if (tok !== P.tok) return; P.playing = false; plUI(); });
  plUI();
}
function plSpeak() {
  var ss = window.speechSynthesis; if (!ss) return;
  if (P.idx >= P.sents.length) { P.playing = false; P.idx = 0; posSet(P.sym, { id: P.id, idx: 0, heard: true }); plUI(); return; }
  var tok = ++P.tok, u = new SpeechSynthesisUtterance(P.sents[P.idx]), v = pickVoice();
  u.lang = v ? v.lang : 'de-DE'; if (v) u.voice = v; u.rate = 0.95;
  u.onend = function () { if (tok !== P.tok || !P.playing) return; P.idx++; plSave(); plSpeak(); };
  u.onerror = function () { if (tok !== P.tok) return; P.playing = false; plUI(); };
  ss.speak(u); plUI();
}
function plStopSpeech() { P.tok++; try { if (AEL) AEL.pause(); } catch (e) {} try { window.speechSynthesis && window.speechSynthesis.cancel(); } catch (e) {} }
function bindPlayer(sym) {
  if (!$('pl')) return;
  var s = null, l = stockList(); for (var i = 0; i < l.length; i++) if (l[i].symbol === sym) s = l[i];
  var sp = speechFor(sym, s);
  if (P.playing && P.sym === sym && P.id === sp.id) { plUI(); }
  else {
    if (P.playing) plStopSpeech();
    P = { sym: sym, sents: splitSents(sp.text), idx: 0, t: 0, playing: false, id: sp.id, tok: P.tok, audio: audioFor(sym, sp) };
    var st = posGet(sym);
    if (st && st.id === sp.id) { P.idx = Math.min(st.idx || 0, P.sents.length); P.t = +st.t || 0; }
    else posSet(sym, { id: sp.id, idx: 0, heard: false });   // neuere Zusammenfassung: alte Position verwerfen
  }
  $('plPlay').onclick = plResume;
  function plResume() {
    if (typeof POD !== 'undefined' && POD.playing) podPause();
    plStopSpeech(); P.playing = true; plMeta();
    if (P.audio) return plAudioPlay();
    if (!window.speechSynthesis) { P.playing = false; return; }
    if (P.idx >= P.sents.length) P.idx = 0; plSpeak();
  }
  function plPauseNow() { if (P.audio && AEL) { try { P.t = AEL.currentTime; } catch (e) {} } P.playing = false; plStopSpeech(); plSave(); plUI(); plMeta(); }
  function plMeta() {
    if (!('mediaSession' in navigator) || (typeof POD !== 'undefined' && POD.playing)) return;
    try {
      navigator.mediaSession.metadata = new MediaMetadata({ title: (s ? s.name : sym), artist: 'Aktien-Radar · Vorlesen' });
      navigator.mediaSession.playbackState = P.playing ? 'playing' : 'paused';
      navigator.mediaSession.setActionHandler('play', function () { if (!P.playing) plResume(); });
      navigator.mediaSession.setActionHandler('pause', plPauseNow);
      try { navigator.mediaSession.setActionHandler('stop', plPauseNow); } catch (e) {}
      navigator.mediaSession.setActionHandler('previoustrack', null); navigator.mediaSession.setActionHandler('nexttrack', null);
    } catch (e) {}
  }
  $('plPause').onclick = plPauseNow;
  $('plStop').onclick = function () {
    if (P.playing) return plPauseNow();   // Stop = sofort anhalten, Stelle bleibt
    P.idx = 0; P.t = 0; if (AEL) try { AEL.currentTime = 0; } catch (e) {} plSave(); plUI();   // im Pausenzustand: von vorn
  };
  plMeta();
  plUI();
}
window.addEventListener('hashchange', function () { if (P.playing && location.hash.indexOf(encodeURIComponent(P.sym)) < 0 && location.hash.indexOf(P.sym) < 0) { P.playing = false; plStopSpeech(); plSave(); } });
document.addEventListener('visibilitychange', function () { if (document.hidden && P.playing && !P.audio) { P.playing = false; plStopSpeech(); plSave(); plUI(); } });

function insightsHtml(sym, q) {
  var x = I && I.stocks ? I.stocks[sym] : null, h = '', i;
  var cur = (q && q.currency) || '';
  h += '<div class="card ins"><h3 style="margin-top:0">Kurz-Zusammenfassung</h3>';
  if (!x) h += '<p class="muted">keine Daten</p>';
  else {
    for (i = 0; i < x.summary.text.length; i++) h += '<p class="sumt">' + esc(x.summary.text[i]) + '</p>';
    if (x.summary.bullets.length) {
      h += '<ul class="sumb">';
      for (i = 0; i < x.summary.bullets.length; i++) { var b = x.summary.bullets[i]; h += '<li>' + offBadge(b) + ' <a href="' + esc(b.link) + '" target="_blank" rel="noopener noreferrer">' + esc(b.title_de || b.title) + '</a>' + origLine(b) + ' <span class="tiny">' + esc(b.source) + ', ' + esc(ago(b.published)) + '</span></li>'; }
      h += '</ul>';
    }
    h += '<p class="tiny">Automatisch aus den Schlagzeilen ausgewählt (offizielle und seriöse Quellen bevorzugt), automatisch ins Deutsche übersetzt.</p>';
  }
  h += '</div><div class="card ins"><h3 style="margin-top:0">Analysten</h3>';
  var a = x && x.analyst ? x.analyst : {};
  if (a.consensus) {
    var c = a.consensus, t = c.kaufen + c.halten + c.verkaufen;
    h += '<div class="cons"><span class="cb" style="flex:' + c.kaufen + '"></span><span class="ch" style="flex:' + c.halten + '"></span><span class="cs" style="flex:' + c.verkaufen + '"></span></div>';
    h += '<div class="kv"><div><span>Kaufen</span>' + c.kaufen + '</div><div><span>Halten</span>' + c.halten + '</div><div><span>Verkaufen</span>' + c.verkaufen + '</div><div><span>Analysten total</span>' + t + '</div></div>';
  } else h += '<p class="muted">Empfehlungen: keine Daten</p>';
  if (a.target) {
    var g = a.target;
    h += '<div class="kv"><div><span>Ø Kursziel</span>' + fmtPrice(g.mean) + ' ' + esc(cur) + '</div><div><span>Potenzial</span>' + (g.upside_pct == null ? 'keine Daten' : '<b class="' + (g.upside_pct >= 0 ? 'up' : 'down') + '">' + fmtSigned(g.upside_pct, 1) + ' %</b>') + '</div><div><span>Höchstes Ziel</span>' + (g.high ? fmtPrice(g.high) : 'keine Daten') + '</div><div><span>Tiefstes Ziel</span>' + (g.low ? fmtPrice(g.low) : 'keine Daten') + '</div></div>';
  } else h += '<p class="muted">Kursziele: keine Daten</p>';
  h += '<div class="kv"><div><span>Nächste Quartalszahlen</span>' + (a.next_earnings ? esc(fmtD(a.next_earnings)) : 'keine Daten') + '</div></div>';
  if (a.changes && a.changes.length) {
    h += '<h3>Hoch-/Herabstufungen (letzte 4 Monate)</h3><ul class="sumb">';
    for (i = 0; i < a.changes.length; i++) { var ch = a.changes[i];
      h += '<li><b>' + esc(ch.firm) + '</b>: ' + esc(ch.action) + (ch.to ? ' (' + (ch.from && ch.from !== ch.to ? esc(ch.from) + ' → ' : '') + esc(ch.to) + ')' : '') + (ch.pt ? ', ' + esc(ch.pt_action || 'Kursziel') + ' ' + (ch.pt_prior ? fmtPrice(ch.pt_prior) + ' → ' : '') + fmtPrice(ch.pt) : '') + ' <span class="tiny">' + esc(fmtD(ch.date)) + '</span></li>'; }
    h += '</ul>';
  }
  if (x && x.analyst_news && x.analyst_news.length) {
    h += '<h3>Analysten in den News</h3><ul class="sumb">';
    for (i = 0; i < x.analyst_news.length; i++) { var n = x.analyst_news[i]; h += '<li><a href="' + esc(n.link) + '" target="_blank" rel="noopener noreferrer">' + esc(n.title_de || n.title) + '</a>' + origLine(n) + ' <span class="tiny">' + esc(n.source) + ', ' + esc(ago(n.published)) + '</span></li>'; }
    h += '</ul>';
  }
  h += '<p class="tiny">Quelle: Yahoo Finance (Konsens der Banken/Analysten)' + (x && x.analyst_at ? ', Stand ' + esc(ago(x.analyst_at)) : '') + '. Keine Anlageberatung.</p></div>';
  return h;
}

var nf = { sym: '', tag: '', q: '', only: false, limit: 60 };
function viewNews() {
  var list = stockList(), h = '<h2 style="margin-top:6px">Alle Nachrichten</h2>';
  h += '<div class="bar"><select id="fSym"><option value="">Alle Aktien</option>';
  var sorted = list.slice().sort(function (a, b) { return a.name.toLowerCase() < b.name.toLowerCase() ? -1 : 1; });
  for (var i = 0; i < sorted.length; i++) h += '<option value="' + esc(sorted[i].symbol) + '">' + esc(sorted[i].name) + ' (' + esc(sorted[i].symbol) + ')</option>';
  h += '</select></div><div class="bar"><select id="fTag"><option value="">Alle Themen</option>';
  for (i = 0; i < TAGS.length; i++) h += '<option value="' + esc(TAGS[i].n) + '">' + esc(TAGS[i].n) + '</option>';
  h += '</select></div><div class="bar"><input type="search" id="fQ" placeholder="Suchen in Titeln" autocomplete="off"></div>';
  h += '<div class="bar"><label class="chk"><input type="checkbox" id="fNew"> Nur neue seit dem letzten Besuch</label><span style="flex:1"></span><button class="small" id="readBtn">Alle als gelesen</button></div>';
  h += '<p class="tiny" id="nCount"></p><div id="nList"></div>';
  $('view').innerHTML = h;
  $('fSym').value = nf.sym; $('fTag').value = nf.tag; $('fQ').value = nf.q; $('fNew').checked = nf.only;
  function upd() { nf.sym = $('fSym').value; nf.tag = $('fTag').value; nf.q = $('fQ').value; nf.only = $('fNew').checked; nf.limit = 60; fillNews(list); }
  $('fSym').onchange = upd; $('fTag').onchange = upd; $('fNew').onchange = upd; $('fQ').oninput = upd;
  $('readBtn').onclick = function () { baseline = Date.now(); lsSet('ar.base', String(baseline)); fillNews(list); };
  fillNews(list);
}
function fillNews(list) {
  var have = {}, i; for (i = 0; i < list.length; i++) have[list[i].symbol] = 1;
  var q = nf.q.toLowerCase().replace(/^\s+|\s+$/g, '');
  var res = (N.items || []).filter(function (x) {
    if (!x.symbols || !x.symbols.length) return false;
    var inList = false; for (var k = 0; k < x.symbols.length; k++) if (have[x.symbols[k]]) inList = true;
    if (!inList) return false;
    if (nf.sym && x.symbols.indexOf(nf.sym) < 0) return false;
    if (nf.tag && x._tags.indexOf(nf.tag) < 0) return false;
    if (nf.only && !isNew(x)) return false;
    if (q && (x.title + ' ' + (x.title_de || '') + ' ' + x.source).toLowerCase().indexOf(q) < 0) return false;
    return true;
  });
  var h = '';
  for (i = 0; i < res.length && i < nf.limit; i++) h += newsHtml(res[i], true);
  if (res.length > nf.limit) h += '<p style="text-align:center"><button id="moreBtn">Mehr anzeigen</button></p>';
  if (!res.length) h = '<p class="muted">Keine Meldungen für diese Auswahl.</p>';
  $('nCount').textContent = res.length + ' Meldungen, neueste zuerst. Nachrichten: Stand ' + ago(N.generated_at) + '.';
  $('nList').innerHTML = h;
  if ($('moreBtn')) $('moreBtn').onclick = function () { nf.limit += 60; fillNews(list); };
}

var mf = { topic: '', q: '', limit: 60 };
function viewMarkt() {
  var topics = (DEF && DEF.market_topics) || [], h = '<h2 style="margin-top:6px">Marktweit</h2><p class="tiny">Themen, die viele Aktien betreffen können: Zölle, Zinsen, Notenbanken, KI-Chips, Exportkontrollen.</p>';
  h += '<div class="bar"><select id="mTopic"><option value="">Alle Themen</option>';
  for (var i = 0; i < topics.length; i++) h += '<option value="' + esc(topics[i].topic) + '">' + esc(topics[i].label) + '</option>';
  h += '</select></div><div class="bar"><input type="search" id="mQ" placeholder="Suchen in Titeln" autocomplete="off"></div><p class="tiny" id="mCount"></p><div id="mList"></div>';
  $('view').innerHTML = h;
  $('mTopic').value = mf.topic; $('mQ').value = mf.q;
  function fill() {
    var q = mf.q.toLowerCase();
    var res = (N.items || []).filter(function (x) { return x.topic && (!mf.topic || x.topic === mf.topic) && (!q || (x.title + ' ' + (x.title_de || '') + ' ' + x.source).toLowerCase().indexOf(q) >= 0); });
    var out = '';
    for (var k = 0; k < res.length && k < mf.limit; k++) out += newsHtml(res[k], false);
    if (res.length > mf.limit) out += '<p style="text-align:center"><button id="mMore">Mehr anzeigen</button></p>';
    if (!res.length) out = '<p class="muted">Keine Meldungen.</p>';
    $('mCount').textContent = res.length + ' Meldungen, neueste zuerst.';
    $('mList').innerHTML = out;
    if ($('mMore')) $('mMore').onclick = function () { mf.limit += 60; fill(); };
  }
  $('mTopic').onchange = function () { mf.topic = $('mTopic').value; mf.limit = 60; fill(); };
  $('mQ').oninput = function () { mf.q = $('mQ').value; mf.limit = 60; fill(); };
  fill();
}

/* ---------- Liste verwalten ---------- */
var addMsg = '';
function loadCatalog() {
  if (CAT) return Promise.resolve(CAT);
  return getJSON('data/catalog.json').then(function (d) { CAT = d.items || []; return CAT; }, function () { CAT = []; return CAT; });
}
function searchStocks(term) {
  var t = term.toLowerCase().replace(/^\s+|\s+$/g, ''), out = [], seen = {};
  if (t.length < 1) return out;
  var pool = [], i, defs = (DEF && DEF.stocks) || [];
  for (i = 0; i < defs.length; i++) pool.push({ s: defs[i].symbol, n: defs[i].name, sec: defs[i].sector });
  pool = pool.concat(CAT || []);
  var scored = [];
  for (i = 0; i < pool.length; i++) {
    var p = pool[i]; if (seen[p.s]) continue;
    var sl = p.s.toLowerCase(), nl = (p.n || '').toLowerCase(), sc = -1;
    if (sl === t) sc = 0; else if (sl.indexOf(t) === 0) sc = 1; else if (nl.indexOf(t) === 0) sc = 2; else if (nl.indexOf(t) >= 0) sc = 3; else if (sl.indexOf(t) >= 0) sc = 4;
    if (sc >= 0) { seen[p.s] = 1; scored.push({ sc: sc, p: p }); }
  }
  scored.sort(function (a, b) { return a.sc - b.sc || (a.p.n < b.p.n ? -1 : 1); });
  for (i = 0; i < scored.length && i < 8; i++) out.push(scored[i].p);
  return out;
}
function inList(sym) { var l = stockList(); for (var i = 0; i < l.length; i++) if (l[i].symbol.toUpperCase() === sym.toUpperCase()) return true; return false; }
function addStock(sym, name, sector) {
  sym = String(sym).replace(/\s+/g, '').toUpperCase();
  if (!/^[A-Z0-9^.=\-]{1,16}$/.test(sym)) { addMsg = 'Ungültiges Kürzel.'; return; }
  var hi = S.hidden.indexOf(sym);
  if (hi >= 0) { S.hidden.splice(hi, 1); addMsg = sym + ' ist wieder in der Liste.'; }
  else if (inList(sym)) { addMsg = sym + ' ist schon in der Liste.'; return; }
  else {
    var isDef = false, defs = (DEF && DEF.stocks) || [];
    for (var i = 0; i < defs.length; i++) if (defs[i].symbol === sym) isDef = true;
    if (!isDef) S.custom.push({ symbol: sym, name: name || sym, sector: sector || 'Sonstige' });
    addMsg = sym + ' hinzugefügt.' + (quoteOf(sym) || isDef ? '' : ' Daten werden beim nächsten Update geladen (siehe unten, "Daten anfordern").');
  }
  S.order = S.order.filter(function (x) { return x !== sym; }); S.order.push(sym);
  saveState();
}
function reqLink(add) { return 'https://github.com/' + REPO + '/issues/new?title=' + encodeURIComponent('Watchlist: ' + add.map(function (a) { return a.symbol; }).join(', ')) + '&body=' + encodeURIComponent('Bitte nicht ändern, wird automatisch verarbeitet:\n\n' + JSON.stringify({ add: add, remove: [] })); }
function pendingList() { return stockList().filter(function (s) { return !quoteOf(s.symbol); }); }
function exportPayload() {
  var add = pendingList().map(function (s) { return { symbol: s.symbol, name: s.name, sector: s.sector }; });
  var defs = (DEF && DEF.stocks) || [], rem = [];
  for (var i = 0; i < S.hidden.length; i++) rem.push(S.hidden[i]);
  return { add: add, remove: rem };
}
function sectorOptions(sel) {
  var o = '', secs = SECTOR_ORDER;
  for (var i = 0; i < secs.length; i++) o += '<option' + (secs[i] === sel ? ' selected' : '') + '>' + esc(secs[i]) + '</option>';
  return o;
}
function viewList() {
  var h = '<h2 style="margin-top:6px">Aktie hinzufügen</h2><p class="tiny">Suche nach Name oder Kürzel (Auswahl aus ca. 500 US-Aktien plus deine Liste). Andere Börsen: Kürzel direkt eingeben, z. B. NESN.SW.</p>';
  h += '<input type="search" id="aq" placeholder="z. B. Nvidia oder NVDA" autocomplete="off" autocapitalize="none"><div id="ares"></div>';
  if (addMsg) h += '<div class="banner" style="border-color:#2e6b44;background:#13261a;color:#9be3b3">' + esc(addMsg) + '</div>';
  var list = orderedList();
  h += '<h2>Meine Liste (' + list.length + ')</h2>';
  for (var i = 0; i < list.length; i++) {
    var s = list[i];
    h += '<div class="res" style="align-items:flex-start"><div style="min-width:0"><b>' + esc(s.symbol) + '</b><span>' + esc(s.name) + (quoteOf(s.symbol) ? '' : ' - noch ohne Daten') + '</span>' +
      '<select data-sec="' + esc(s.symbol) + '" style="margin-top:6px;padding:6px 8px;font-size:14px">' + sectorOptions(s.sector) + '</select></div>' +
      '<div style="display:flex;gap:6px;align-items:center"><button class="small" data-mv="up" data-s="' + esc(s.symbol) + '" aria-label="Nach oben">' + MV_UP + '</button><button class="small" data-mv="down" data-s="' + esc(s.symbol) + '" aria-label="Nach unten">' + MV_DN + '</button><button class="small danger" data-del="' + esc(s.symbol) + '">Entfernen</button></div></div>';
  }
  var pend = pendingList();
  h += '<h2>Daten anfordern</h2><div class="card">';
  if (pend.length || S.hidden.length) {
    h += '<p class="tiny" style="margin-top:0">' + (pend.length ? 'Neu hinzugefügt, aber noch ohne Daten: <b>' + esc(pend.map(function (p) { return p.symbol; }).join(', ')) + '</b>. ' : '') + 'Die Kurse und Nachrichten holt eine GitHub-Action. Damit sie neue Aktien kennt, muss sie davon erfahren. Ohne Server und ohne Zugangsdaten auf dem Handy geht das so:</p>';
  } else h += '<p class="tiny" style="margin-top:0">Alle Aktien in deiner Liste haben Daten. Wenn du etwas hinzufügst, das noch keine Daten hat, erscheinen hier die Wege dafür.</p>';
  h += '<p class="tiny"><b>Weg 1 (ohne Mika):</b> "Per GitHub anfordern" öffnet ein vorbereitetes Issue. Du musst auf github.com angemeldet sein und "Submit new issue" tippen. Eine Action trägt die Aktien ein und holt sofort die Daten (ca. 1 bis 2 Minuten, dann hier "Aktualisieren").</p>';
  h += '<p class="tiny"><b>Weg 2:</b> "Watchlist exportieren" teilt den Stand per Teilen-Menü (z. B. an Mika), der sie einträgt.</p>';
  h += '<div style="display:flex;gap:8px;flex-wrap:wrap"><a class="pill" id="ghLink" target="_blank" rel="noopener noreferrer" style="padding:10px 16px;color:var(--text)">Per GitHub anfordern</a><button id="expBtn" class="primary">Watchlist exportieren</button></div><p class="tiny" id="expMsg"></p></div>';
  h += '<h2>Fragen (Gemini)</h2><div class="card"><p class="tiny" style="margin-top:0">' + (askKey() ? 'Ein Gemini-Schlüssel ist auf diesem Gerät gespeichert' + (askKeySrc() === 'lehrerin' ? ' (von der Lehrerin übernommen)' : '') + '. Er bleibt nur auf diesem Gerät.' : 'Für „Fragen“ braucht es einmalig deinen Gemini-Schlüssel. Er wird nur auf diesem Gerät gespeichert, nie im Code oder im Internet.') + '</p><input type="password" id="gkIn" placeholder="Gemini-Schlüssel einfügen" autocomplete="off" autocapitalize="none" spellcheck="false"><p style="margin:8px 0 0"><button id="gkSave" class="primary small">Speichern</button> ' + (lsGet('ar.gkey') ? '<button id="gkDel" class="small danger">Schlüssel löschen</button>' : '') + '</p><p class="tiny" id="gkMsg"></p></div>';
  h += '<h2>Anzeige</h2><p><button id="resetBtn" class="danger">Standardliste wiederherstellen</button></p><p class="tiny">Setzt entfernte Aktien, eigene Reihenfolge und eigene Sektoren zurück und löscht lokal hinzugefügte Aktien.</p>';
  $('view').innerHTML = h;
  var aq = $('aq');
  function showRes() {
    var r = searchStocks(aq.value), o = '';
    for (var k = 0; k < r.length; k++) {
      var already = inList(r[k].s);
      o += '<div class="res"><div style="min-width:0"><b>' + esc(r[k].s) + '</b><span>' + esc(r[k].n) + ' - ' + esc(r[k].sec || '') + '</span></div><button class="small primary" data-add="' + esc(r[k].s) + '" data-n="' + esc(r[k].n) + '" data-sec="' + esc(r[k].sec || 'Sonstige') + '"' + (already ? ' disabled' : '') + '>' + (already ? 'In Liste' : 'Hinzufügen') + '</button></div>';
    }
    var t = aq.value.replace(/\s+/g, '');
    if (t && /^[A-Za-z0-9^.=\-]{1,16}$/.test(t) && !inList(t)) o += '<div class="res"><div><b>' + esc(t.toUpperCase()) + '</b><span>Kürzel direkt hinzufügen (Name und Sektor frei wählbar)</span><input type="text" id="dName" placeholder="Name (optional)" style="margin-top:6px;padding:6px 8px"><select id="dSec" style="margin-top:6px;padding:6px 8px">' + sectorOptions('Sonstige') + '</select></div><button class="small primary" id="dAdd" data-sym="' + esc(t) + '">Hinzufügen</button></div>';
    $('ares').innerHTML = o;
  }
  loadCatalog().then(function () { if (aq.value) showRes(); });
  aq.oninput = showRes;
  $('ares').onclick = function (e) {
    var b = e.target; while (b && b !== this && !b.getAttribute('data-add') && b.id !== 'dAdd') b = b.parentNode;
    if (!b || b === this) return;
    if (b.id === 'dAdd') addStock(b.getAttribute('data-sym'), $('dName').value, $('dSec').value);
    else addStock(b.getAttribute('data-add'), b.getAttribute('data-n'), b.getAttribute('data-sec'));
    viewList();
  };
  var payload = exportPayload(), json = JSON.stringify(payload);
  $('ghLink').href = 'https://github.com/' + REPO + '/issues/new?title=' + encodeURIComponent('Watchlist: Änderung') + '&body=' + encodeURIComponent('Bitte nicht ändern, wird automatisch verarbeitet:\n\n' + json);
  $('expBtn').onclick = function () {
    var text = 'Aktien-Radar: Watchlist-Änderung für watchlist.json\n' + json;
    function copyFallback() {
      try { navigator.clipboard.writeText(text).then(function () { $('expMsg').textContent = 'In die Zwischenablage kopiert. Jetzt bei Mika einfügen.'; }, function () { $('expMsg').textContent = 'Teilen nicht möglich. Text: ' + text; }); }
      catch (e) { $('expMsg').textContent = 'Teilen nicht möglich. Text: ' + text; }
    }
    if (navigator.share) { navigator.share({ title: 'Aktien-Radar Watchlist', text: text }).then(function () { $('expMsg').textContent = 'Geteilt.'; }, function (e) { if (e && e.name !== 'AbortError') copyFallback(); }); }
    else copyFallback();
  };
  $('gkSave').onclick = function () { var v = $('gkIn').value.trim(); if (!/^[A-Za-z0-9_\-]{20,}$/.test(v)) { $('gkMsg').textContent = 'Das sieht nicht wie ein Gemini-Schlüssel aus.'; return; } lsSet('ar.gkey', v); viewList(); };
  if ($('gkDel')) $('gkDel').onclick = function () { try { localStorage.removeItem('ar.gkey'); } catch (e) {} viewList(); };
  $('resetBtn').onclick = function () { if (confirm('Standardliste wiederherstellen? Eigene Änderungen gehen verloren.')) { S.hidden = []; S.custom = []; S.order = []; S.sec = {}; saveState(); addMsg = ''; viewList(); } };
}

/* ---------- Ereignisse (Reihenfolge, Entfernen, Sektor) ---------- */
function move(sym, dir) {
  var l = orderedList().map(function (x) { return x.symbol; }), i = l.indexOf(sym), j = i + (dir === 'up' ? -1 : 1);
  if (i < 0 || j < 0 || j >= l.length) return;
  var t = l[i]; l[i] = l[j]; l[j] = t; S.order = l; saveState();
}
document.addEventListener('click', function (e) {
  var b = e.target; while (b && b !== document && !(b.getAttribute && (b.getAttribute('data-mv') || b.getAttribute('data-del')))) b = b.parentNode;
  if (!b || b === document) return;
  var sym = b.getAttribute('data-s') || b.getAttribute('data-del');
  if (b.getAttribute('data-mv')) { e.preventDefault(); e.stopPropagation(); move(sym, b.getAttribute('data-mv')); route(); }
  else if (b.getAttribute('data-del')) {
    if (!confirm(sym + ' aus der Liste entfernen?')) return;
    var ci = -1; for (var i = 0; i < S.custom.length; i++) if (S.custom[i].symbol === sym) ci = i;
    if (ci >= 0) S.custom.splice(ci, 1); else if (S.hidden.indexOf(sym) < 0) S.hidden.push(sym);
    S.order = S.order.filter(function (x) { return x !== sym; });
    saveState(); addMsg = sym + ' entfernt.'; route();
  }
}, true);
document.addEventListener('change', function (e) {
  var t = e.target; if (t && t.getAttribute && t.getAttribute('data-sec') && t.tagName === 'SELECT') { S.sec[t.getAttribute('data-sec')] = t.value; saveState(); }
});

/* ---------- Routing ---------- */
function setTab(t) {
  var a = document.querySelectorAll('#tabs a');
  for (var i = 0; i < a.length; i++) a[i].className = a[i].getAttribute('data-t') === t ? 'on' : '';
}
function route() {
  var h = location.hash || '#/', m;
  try {
    if ((m = /^#\/s\/(.+)$/.exec(h))) { setTab('home'); viewDetail(decodeURIComponent(m[1])); }
    else if (h === '#/news') { setTab('news'); viewNews(); }
    else if (h === '#/markt') { setTab('markt'); viewMarkt(); }
    else if (h === '#/liste') { setTab('liste'); viewList(); }
    else { setTab('home'); viewHome(); }
  } catch (err) { showErr('Anzeige-Fehler: ' + err.message); }
  updatePill();
}
/* ---------- Zurück zur Liste: Position merken ---------- */
var POS_KEY = 'ar_lastpos';
function getPos() { try { return JSON.parse(sessionStorage.getItem(POS_KEY) || localStorage.getItem(POS_KEY) || 'null'); } catch (e) { return null; } }
function backHash() { var p = getPos(); return p && p.view === '#/liste' ? '#/liste' : '#/'; }
document.addEventListener('click', function (e) {
  var a = e.target && e.target.closest ? e.target.closest('a.row') : null;
  if (!a) return;
  var m = /#\/s\/(.+)$/.exec(a.getAttribute('href') || '');
  if (!m) return;
  var v = location.hash === '#/liste' ? '#/liste' : '#/';
  var d = JSON.stringify({ sym: decodeURIComponent(m[1]), y: window.scrollY || 0, view: v });
  try { sessionStorage.setItem(POS_KEY, d); localStorage.setItem(POS_KEY, d); } catch (er) {}
}, true);
function restorePos(tries) {
  var p = getPos(), h = location.hash || '#/';
  if (h === '#') h = '#/';
  if (!p || p.view !== h) { window.scrollTo(0, 0); return; }
  var rows = document.querySelectorAll('#view a.row'), el = null;
  for (var i = 0; i < rows.length; i++) if (rows[i].getAttribute('href') === '#/s/' + encodeURIComponent(p.sym)) { el = rows[i]; break; }
  if (!el) { if ((tries || 0) < 20) setTimeout(function () { restorePos((tries || 0) + 1); }, 150); else window.scrollTo(0, p.y || 0); return; }
  window.scrollTo(0, p.y || 0);
  var r = el.getBoundingClientRect();
  if (r.top < 60 || r.bottom > window.innerHeight - 90) window.scrollTo(0, Math.max(0, window.scrollY + r.top - window.innerHeight / 3));
  el.classList.add('rowFlash');
  setTimeout(function () { el.classList.remove('rowFlash'); }, 1800);
}
window.addEventListener('hashchange', function () {
  route();
  var h = location.hash || '#/';
  if (h === '#/' || h === '#' || h === '#/liste') restorePos(0); else window.scrollTo(0, 0);
});
function updatePill() {
  var p = $('netPill'), on = navigator.onLine !== false, qa = Q && Q.generated_at;
  p.textContent = (on ? 'Online' : 'Offline') + (qa ? ' - Stand ' + ago(qa) : '');
  p.className = 'pill' + (on ? '' : ' warn');
}
var lastLoad = 0, loading = false;
function reload(manual) {
  if (loading) return; loading = true;
  var b = $('reloadBtn'); if (b) b.textContent = 'Lade...';
  loadData().then(function () { lastLoad = Date.now(); loading = false; if (manual || !/^#\/(liste|s\/)/.test(location.hash)) route(); else updatePill(); }, function (e) { loading = false; showErr('Laden fehlgeschlagen: ' + e.message); });
}
window.addEventListener('online', function () { reload(false); });
window.addEventListener('offline', updatePill);
// Akku schonen: kein Timer/Polling. Neu geladen wird nur beim Öffnen, beim Zurückholen in den Vordergrund und per Knopf.
document.addEventListener('visibilitychange', function () { touchLast(); if (document.visibilityState === 'visible') { if (Date.now() - lastLoad > 30 * 1000) reload(false); else updatePill(); } });
window.addEventListener('pageshow', function (e) { if (e.persisted && Date.now() - lastLoad > 30 * 1000) reload(false); });

/* ---------- Start ---------- */
initBaseline();
loadData().then(function () { lastLoad = Date.now(); route(); }, function (e) { showErr('Start fehlgeschlagen: ' + e.message); });
if ('serviceWorker' in navigator && /^https?:$/.test(location.protocol)) {
  var hadCtrl = !!navigator.serviceWorker.controller;
  navigator.serviceWorker.addEventListener('controllerchange', function () {
    // neue App-Version hat uebernommen: einmal neu laden (Schutz gegen Endlosschleife)
    if (!hadCtrl) return;
    var last = 0; try { last = +sessionStorage.getItem('ar.swReload') || 0; } catch (e) {}
    if (Date.now() - last < 30000) return;
    try { sessionStorage.setItem('ar.swReload', String(Date.now())); } catch (e) {}
    location.reload();
  });
  navigator.serviceWorker.register('sw.js', { updateViaCache: 'none' }).then(function (reg) {
    document.addEventListener('visibilitychange', function () { if (document.visibilityState === 'visible') reg.update().catch(function () {}); });
  }).catch(function (e) { showErr('Offline-Modus nicht verfügbar: ' + e.message, 'warn'); });
}
/* ---------- Fragen zur Aktie (Gemini + Google-Suche) ----------
   Schlüssel nur auf dem Gerät: eigener (ar.gkey) oder der Lehrerin (gleiche Herkunft ayoub971-prog.github.io). */
var ASK_MODELS = ['gemini-3.5-flash-lite', 'gemini-2.5-flash'];
var askMem = null, ASK_HIST = {}, ASK_TIMEOUT = +(lsGet('ar.askto') || 45000);
function lehrerinKey() { try { var v = localStorage.getItem('lehrerin.key'); return v ? JSON.parse(v) : ''; } catch (e) { return ''; } }
function askKeySrc() { return lsGet('ar.gkey') ? 'eigen' : (lehrerinKey() || askMem ? 'lehrerin' : ''); }
function askKey() { return lsGet('ar.gkey') || lehrerinKey() || askMem || ''; }
// Lehrerin speichert den Schlüssel zusätzlich in IndexedDB 'lehrerin-kv' (gleiche Herkunft)
(function () { try { var r = indexedDB.open('lehrerin-kv'); r.onupgradeneeded = function () { try { r.transaction.abort(); } catch (e) {} };
  r.onsuccess = function () { var d = r.result; try { if (!d.objectStoreNames.contains('kv')) { d.close(); return; } var g = d.transaction('kv').objectStore('kv').get('key'); g.onsuccess = function () { if (g.result) askMem = String(g.result); d.close(); }; } catch (e) { d.close(); } }; } catch (e) {} })();
function askHtml(s) {
  return '<div class="card" id="askCard" style="margin-bottom:80px;scroll-margin-top:12px"><div class="h" style="font-weight:700;color:var(--accent);letter-spacing:.06em;font-size:14px">🤖 KI FRAGEN ZU ' + esc(s.name.toUpperCase()) + '</div>' +
    '<p class="tiny" style="margin:4px 0 8px">Frag alles zu dieser Aktie, z. B. „Warum hat die Firma Probleme?“, „Was sagt UBS?“ oder „Was bedeutet das?“. Danach kannst du nachfragen („Warum?“, „Ich will mehr wissen“). Die KI sucht im Internet und nennt Quellen.</p><div id="askOut"></div>' +
    '<div style="display:flex;gap:8px"><input type="search" id="askIn" placeholder="Deine Frage …" autocomplete="off" style="flex:1"><button id="askMic" aria-label="Sprechen">🎤</button></div>' +
    '<p style="margin:8px 0 0"><button id="askGo" class="primary">Fragen</button> <button id="askSpeak" hidden>▶ Vorlesen</button></p><button id="askNew" class="small" hidden>Neues Gespräch</button></p><p class="tiny" id="askHint"></p></div>';
}
function askErr(e) {
  var st = e && e.status, m = (e && e.message) || '';
  if (m === 'TIMEOUT') return 'Gemini hat nach 45 Sekunden nicht geantwortet. Bitte nochmals versuchen (evtl. ist die Verbindung schwach).';
  if (m === 'NOKEY') return 'Es fehlt der Gemini-Schlüssel auf diesem iPhone. Tippe unten auf „Schlüssel eintragen“ und füge ihn einmal ein.';
  if (st === 429 || /quota|exhausted|rate/i.test(m)) return 'Gemini-Kontingent erschöpft (Fehler ' + (st || '429') + '). Das Gratis-Kontingent ist für den Moment aufgebraucht. Bitte später nochmals versuchen.';
  if (st === 400 && /api key|API_KEY/i.test(m) || st === 401 || st === 403 && /key|permission|denied/i.test(m)) return 'Der Gemini-Schlüssel wird abgelehnt (Fehler ' + st + '). Bitte „Schlüssel eintragen“ und einen gültigen Schlüssel einfügen.';
  if (!st) return 'Keine Verbindung zu Gemini (' + (m || 'Netzwerkfehler') + '). Bitte Internet prüfen und nochmals versuchen.';
  return 'Gemini meldet Fehler ' + st + ': ' + m.slice(0, 200);
}
function askNeedsKeyBtn(e) { var st = e && e.status, m = (e && e.message) || ''; return m === 'NOKEY' || st === 401 || (st === 400 && /api key|API_KEY/i.test(m)) || (st === 403 && /key|permission|denied/i.test(m)); }
// Gratis-Schlüssel: Google-Suche ist dort laut Google nicht verfügbar -> Fehler. Dann ohne Suche, mit den Meldungen der App.
function askSearchBlocked(e) { var st = e && e.status, m = (e && e.message) || ''; return st === 429 || /search|ground|tool|billing|quota|limit|paid|not supported|not available/i.test(m) && (st === 400 || st === 403 || st === 429); }
function askMaterial(sym) {
  var it = ((N && N.items) || []).filter(function (x) { return x.symbols && x.symbols.indexOf(sym) >= 0; }).slice(0, 40), out = [];
  for (var i = 0; i < it.length; i++) out.push({ n: i + 1, t: it[i].title_de || it[i].title, src: it[i].source || '', d: (it[i].published || '').slice(0, 10), uri: it[i].link });
  return out;
}
function askGemini(body) {
  var k = askKey(); if (!k) return Promise.reject(new Error('NOKEY'));
  var i = 0;
  function go() {
    var ac = null; try { ac = new AbortController(); } catch (e) {}
    var opt = { method: 'POST', headers: { 'Content-Type': 'application/json', 'x-goog-api-key': k }, body: JSON.stringify(body) }; if (ac) opt.signal = ac.signal;
    var tm, timeout = new Promise(function (_, rej) { tm = setTimeout(function () { try { ac && ac.abort(); } catch (e) {} var e = new Error('TIMEOUT'); rej(e); }, ASK_TIMEOUT); });
    return Promise.race([fetch('https://generativelanguage.googleapis.com/v1beta/models/' + ASK_MODELS[i] + ':generateContent', opt), timeout])
      .then(function (r) { clearTimeout(tm); return r; }, function (e) { clearTimeout(tm); if (e && e.name === 'AbortError') e = new Error('TIMEOUT'); throw e; })
      .then(function (r) { return r.json().then(function (j) { if (!r.ok) { var e = new Error((j.error && j.error.message) || ('HTTP ' + r.status)); e.status = r.status; throw e; } return j; }); })
      .catch(function (e) { if (i < ASK_MODELS.length - 1 && (e.status === 404 || (e.status === 400 && /model|tool|search/i.test(e.message)))) { i++; return go(); } throw e; });
  }
  return go();
}
function askGoKey() { location.hash = '#/liste'; setTimeout(function () { var g = $('gkIn'); if (g) { g.scrollIntoView({ block: 'center' }); g.focus(); } }, 400); }
function askLinkify(t) { return esc(t).replace(/\*\*([^*]+)\*\*/g, '<b>$1</b>').replace(/\n/g, '<br>'); }
function bindAsk(s) {
  if (!$('askGo')) return;
  if ($('askJump')) $('askJump').onclick = function () { $('askCard').scrollIntoView({ behavior: 'smooth', block: 'start' }); setTimeout(function () { $('askIn').focus(); }, 400); };
  var last = '';
  var hist = ASK_HIST[s.symbol] || (ASK_HIST[s.symbol] = []), busy = false, busyIv = null;
  function render() {
    var h = '';
    for (var i = 0; i < hist.length; i++) {
      var m = hist[i];
      if (m.err) { h += '<div style="margin:10px 0;padding:8px 12px;border-radius:12px;border:1px solid #7a3030;color:#ff9a96">⚠️ ' + esc(m.text) + (m.keyBtn ? '<br><button type="button" class="small primary askKeyB" style="margin-top:8px">Schlüssel eintragen</button>' : '') + '</div>'; continue; }
      if (m.role === 'user') h += '<div style="margin:10px 0 0 30px;padding:8px 12px;border-radius:14px;background:var(--panel2);text-align:right">' + esc(m.text) + '</div>';
      else {
        h += '<div style="margin:10px 0;line-height:1.5">' + askLinkify(m.text) + '</div>';
        if (m.src && m.src.length) { h += '<div class="tiny"><b>Quellen:</b>'; for (var k = 0; k < m.src.length && k < 8; k++) h += '<br>' + (/^\[/.test(m.src[k].title || '') ? '' : (k + 1) + '. ') + '<a href="' + esc(m.src[k].uri) + '" target="_blank" rel="noopener noreferrer">' + esc(m.src[k].title || m.src[k].uri) + '</a>'; h += '</div>'; }
      }
    }
    if (hist.length) h += '<p class="tiny">Antworten von Gemini. Bitte Quellen prüfen. Keine Anlageberatung.</p>';
    if (busy) h += '<div id="askBusy" style="margin:10px 0;color:var(--accent);font-weight:600">🤖 Denke nach … <span class="tiny" id="askBusyT"></span></div>';
    $('askOut').innerHTML = h; $('askNew').hidden = !hist.length;
    var kb = document.querySelectorAll('.askKeyB'); for (var q = 0; q < kb.length; q++) kb[q].onclick = askGoKey;
    if (hist.length || busy) { var kids = $('askOut').children, lastEl = kids[kids.length - 1]; if (busy) lastEl = $('askBusy'); else { for (var z = kids.length - 1; z >= 0; z--) if (!/tiny/.test(kids[z].className)) { lastEl = kids[z]; break; } } if (lastEl && lastEl.scrollIntoView) setTimeout(function () { try { lastEl.scrollIntoView({ behavior: 'smooth', block: 'start' }); } catch (e) { lastEl.scrollIntoView(); } }, 50); }
    var la = null; for (i = hist.length - 1; i >= 0; i--) if (hist[i].role === 'model' && !hist[i].err) { la = hist[i]; break; }
    last = la ? la.text : ''; $('askSpeak').hidden = !la;
  }
  render();
  $('askNew').onclick = function () { hist.length = 0; render(); $('askIn').focus(); };
  $('askGo').onclick = function () { try { askRun(); } catch (ex) { busy = false; clearInterval(busyIv); $('askGo').disabled = false; hist.push({ role: 'model', err: true, text: 'Interner Fehler: ' + (ex && ex.message || ex) }); render(); } };
  function askRun() {
    var qq = $('askIn').value.trim(); if (!qq) { $('askHint').textContent = 'Schreib oder sprich zuerst eine Frage.'; return; }
    if (!askKey()) { $('askHint').innerHTML = esc(askErr(new Error('NOKEY'))) + '<br><button type="button" id="askKeyBtn" class="small primary" style="margin-top:8px">Schlüssel eintragen</button>'; $('askKeyBtn').onclick = askGoKey; return; }
    hist.push({ role: 'user', text: qq }); $('askIn').value = ''; try { $('askIn').blur(); } catch (e) {}
    busy = true; var t0 = Date.now(); render(); $('askHint').textContent = ''; $('askGo').disabled = true;
    busyIv = setInterval(function () { var el = $('askBusyT'); if (el) el.textContent = Math.round((Date.now() - t0) / 1000) + ' s'; }, 1000);
    var today = new Date().toISOString().slice(0, 10);
    var sys = 'Heute ist ' + today + '. Du hilfst einem Privatanleger aus der Schweiz, die Aktie ' + s.name + ' (Kürzel ' + s.symbol + ') zu verstehen. Alle Fragen beziehen sich auf diese Firma, ausser er sagt etwas anderes. ' +
      'Suche für jede Antwort mit Google nach aktuellen, seriösen Quellen. Antworte auf Deutsch (Schweizer Rechtschreibung, kein ß), kurz, klar und einfach, wie ein guter Journalist: höchstens 6 kurze Sätze, schwierige Wörter kurz erklären. ' +
      'Nenne bei Fakten, wer es wann gesagt hat (mit Datum). Erfinde nichts: nur, was in den gefundenen Quellen steht. Bei Nachfragen wie „Warum?“ oder „Ich will mehr wissen“ beziehe dich auf das bisherige Gespräch. ' +
      'Wenn du nichts Verlässliches findest, schreibe genau: „Dazu habe ich keine verlässliche Quelle gefunden.“ Keine Kauf- oder Verkaufsempfehlung.';
    var contents = hist.filter(function (m) { return !m.err; }).slice(-12).map(function (m) { return { role: m.role, parts: [{ text: m.text }] }; });
    function show(txt, src, note) { busy = false; hist.push({ role: 'model', text: txt + (note ? '\n\n' + note : ''), src: src }); $('askHint').innerHTML = ''; render(); }
    function fail(e) { busy = false; hist.push({ role: 'model', err: true, text: askErr(e), keyBtn: askNeedsKeyBtn(e) }); render(); }
    function textOf(j) { var c = j.candidates && j.candidates[0]; return { c: c, txt: c && c.content && c.content.parts ? c.content.parts.map(function (p) { return p.text || ''; }).join('').trim() : '' }; }
    askGemini({ systemInstruction: { parts: [{ text: sys }] }, contents: contents, tools: [{ google_search: {} }], generationConfig: { temperature: 0.2, maxOutputTokens: 900 } })
      .then(function (j) {
        try {
        var r = textOf(j), gm = (r.c && r.c.groundingMetadata) || {}, ch = gm.groundingChunks || [], seen = {}, src = [];
        for (var i = 0; i < ch.length; i++) { var w = ch[i].web; if (w && w.uri && !seen[w.uri]) { seen[w.uri] = 1; src.push(w); } }
        if (!r.txt) return show('Dazu habe ich keine verlässliche Quelle gefunden.', []);
        show(r.txt, src, src.length ? '' : '(Hinweis: Gemini hat zu dieser Antwort keine Links mitgeliefert. Bitte mit Vorsicht lesen.)');
        } catch (ex) { fail(ex); }
      }, function (e) {
        try {
        if (!askSearchBlocked(e)) return fail(e);
        // Ohne Internetsuche: nur aus den gesammelten Meldungen der App antworten
        var mat = askMaterial(s.symbol);
        if (!mat.length) return fail(e);
        $('askHint').textContent = 'Internetsuche nicht verfügbar – ich antworte aus den Meldungen der App …';
        var sys2 = sys.replace(/Suche für jede Antwort mit Google[^.]*\./, '') + ' Du hast KEINE Internetsuche. Nutze NUR die nummerierten MELDUNGEN unten und setze nach jeder Aussage die Nummer in eckigen Klammern, z. B. [3]. Steht die Antwort nicht in den Meldungen, schreibe genau: „Dazu habe ich in den Meldungen der App nichts gefunden.“\n\nMELDUNGEN:\n' +
          mat.map(function (m) { return '[' + m.n + '] ' + m.d + ' – ' + m.src + ': ' + m.t; }).join('\n');
        return askGemini({ systemInstruction: { parts: [{ text: sys2 }] }, contents: contents, generationConfig: { temperature: 0.2, maxOutputTokens: 900 } }).then(function (j) {
          var r = textOf(j), used = {}, src = [];
          (r.txt.match(/\[(\d{1,2})\]/g) || []).forEach(function (x) { var n = +x.replace(/\D/g, ''); if (mat[n - 1] && !used[n]) { used[n] = 1; src.push({ uri: mat[n - 1].uri, title: '[' + n + '] ' + mat[n - 1].src + ', ' + mat[n - 1].d + ': ' + mat[n - 1].t }); } });
          show(r.txt || 'Dazu habe ich in den Meldungen der App nichts gefunden.', src, '(Ohne Internetsuche: Mit dem Gratis-Schlüssel erlaubt Google keine Suche, darum stammt die Antwort nur aus den Meldungen, die die App gesammelt hat.)');
        }, fail);
        } catch (ex) { fail(ex); }
      })
      .then(null, function (ex) { fail(ex); })
      .then(function () { busy = false; clearInterval(busyIv); var g = $('askGo'); if (g) g.disabled = false; if ($('askBusy')) render(); });
  }
  $('askIn').onkeydown = function (e) { if (e.key === 'Enter') { e.preventDefault(); $('askGo').onclick(); } };
  $('askSpeak').onclick = function () {
    var ss = window.speechSynthesis; if (!ss) return;
    if (ss.speaking) { ss.cancel(); $('askSpeak').textContent = '▶ Vorlesen'; return; }
    try { if (P.playing) { P.playing = false; plStopSpeech(); plSave(); plUI(); } } catch (e) {}
    var u = new SpeechSynthesisUtterance(last.replace(/\*\*/g, '')); u.lang = 'de-CH'; var v = pickVoice(); if (v) { u.voice = v; u.lang = v.lang; }
    u.onend = u.onerror = function () { $('askSpeak') && ($('askSpeak').textContent = '▶ Vorlesen'); };
    ss.cancel(); ss.speak(u); $('askSpeak').textContent = '■ Stop';
  };
  var mr = null, recog = null;
  $('askMic').onclick = function () {
    var btn = $('askMic');
    if (mr && mr.state === 'recording') { mr.stop(); return; }
    if (recog) { recog.stop(); return; }
    var IOS = /iPhone|iPad|iPod/.test(navigator.userAgent) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
    var SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (SR && !IOS) {
      recog = new SR(); recog.lang = 'de-CH'; recog.interimResults = true;
      recog.onresult = function (e) { var t = ''; for (var i = 0; i < e.results.length; i++) t += e.results[i][0].transcript; $('askIn').value = t; };
      recog.onend = function () { recog = null; btn.textContent = '🎤'; if ($('askIn').value.trim()) $('askGo').onclick(); };
      recog.onerror = function (e) { $('askHint').textContent = 'Spracheingabe ging nicht (' + e.error + '). Du kannst auch tippen.'; };
      recog.start(); btn.textContent = '⏹'; $('askHint').textContent = 'Ich höre zu …'; return;
    }
    if (!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia && window.MediaRecorder)) { $('askHint').textContent = 'Tippe auf das 🎤 der iPhone-Tastatur.'; return; }
    if (!askKey()) { $('askHint').textContent = askErr(new Error('NOKEY')); return; }
    navigator.mediaDevices.getUserMedia({ audio: true }).then(function (stream) {
      var type = ['audio/mp4', 'audio/webm;codecs=opus', 'audio/webm'].filter(function (t) { return MediaRecorder.isTypeSupported && MediaRecorder.isTypeSupported(t); })[0] || '';
      mr = type ? new MediaRecorder(stream, { mimeType: type }) : new MediaRecorder(stream); var parts = [];
      mr.ondataavailable = function (e) { if (e.data && e.data.size) parts.push(e.data); };
      mr.onstop = function () {
        stream.getTracks().forEach(function (t) { t.stop(); }); btn.textContent = '🎤';
        var mime = (mr.mimeType || type || 'audio/mp4').split(';')[0], blob = new Blob(parts, { type: mime }); mr = null;
        if (blob.size < 800) { $('askHint').textContent = 'Ich habe nichts gehört.'; return; }
        $('askHint').textContent = 'Wird erkannt …';
        var fr = new FileReader(); fr.onload = function () {
          askGemini({ contents: [{ role: 'user', parts: [{ inlineData: { mimeType: mime, data: String(fr.result).split(',')[1] } }, { text: 'Schreib genau auf, was in dieser Aufnahme auf Deutsch (evtl. Schweizerdeutsch) gesagt wird, in Hochdeutsch. Gib NUR den Text zurück. Wenn nichts Verständliches gesagt wird, gib „-“ zurück.' }] }], generationConfig: { temperature: 0, maxOutputTokens: 200 } })
            .then(function (j) { var t = ((j.candidates && j.candidates[0] && j.candidates[0].content.parts[0].text) || '').trim().replace(/^["„“]|["“”]$/g, ''); if (!t || t === '-') { $('askHint').textContent = 'Ich habe dich nicht verstanden. Nochmals?'; return; } $('askIn').value = t; $('askGo').onclick(); }, function (e) { $('askHint').textContent = askErr(e); });
        }; fr.readAsDataURL(blob);
      };
      mr.start(250); btn.textContent = '⏹'; $('askHint').textContent = 'Ich höre zu … (zum Beenden ⏹ antippen)';
      setTimeout(function () { if (mr && mr.state === 'recording') mr.stop(); }, 20000);
    }, function () { $('askHint').textContent = 'Das Mikrofon ist nicht erlaubt. Bitte in den iPhone-Einstellungen › Safari › Mikrofon erlauben.'; });
  };
}

/* ===== Podcast: alle Aktien am Stück (data/podcast.json), Segment für Segment ===== */
var POD = { doc: null, segs: [], i: 0, sents: [], si: 0, t: 0, playing: false, tok: 0, el: null, gen: null };
function podLoad() {
  return getJSON('data/podcast.json').then(function (d) { POD.doc = d; }, function () { POD.doc = null; });
}
function podBuild() {
  var d = POD.doc || {}, map = {}, segs = [], l = orderedList(), i;
  (d.segments || []).forEach(function (x) { map[x.symbol] = x; });
  for (i = 0; i < l.length; i++) {
    var s = l[i], x = map[s.symbol], sp = speechFor(s.symbol, s);
    var text = x ? x.text : (sp.ai ? (sp.text.toLowerCase().indexOf(s.name.toLowerCase()) === 0 ? sp.text : s.name + ': ' + sp.text) : null);
    if (!text) continue;
    var au = audioFor(s.symbol, sp);
    segs.push({ sym: s.symbol, name: s.name, text: text, audio: (x && au) ? au : null });
  }
  var n = segs.length;
  segs.unshift({ sym: '_intro', name: 'Einleitung', text: d.intro || ('Willkommen beim Aktien-Radar. Heute geht es um ' + n + ' Aktien aus deiner Liste. Alles stammt aus den gesammelten Meldungen. Keine Anlageberatung.') });
  segs.push({ sym: '_outro', name: 'Schluss', text: d.outro || 'Das war der Aktien-Radar-Überblick. Keine Anlageberatung.' });
  POD.segs = segs; POD.gen = (d.generated_at || '') + '|' + segs.map(function (x) { return x.sym; }).join(',');
}
function podSave() { var g = POD.segs[POD.i]; lsSet('ar.pod', JSON.stringify({ gen: POD.gen, sym: g && g.sym, h: g && hashStr(g.text + (g.audio ? g.audio.hash : '')), si: POD.si, t: POD.t })); }
function podRestore() {
  var o = null; try { o = JSON.parse(lsGet('ar.pod') || 'null'); } catch (e) {}
  POD.i = 0; POD.si = 0; POD.t = 0;
  if (!o) return;
  for (var i = 0; i < POD.segs.length; i++) if (POD.segs[i].sym === o.sym) { POD.i = i; var g = POD.segs[i]; if (o.h === hashStr(g.text + (g.audio ? g.audio.hash : ''))) { POD.si = o.si || 0; POD.t = o.t || 0; } }
}
function podUI() {
  var b = $('podBtn'); if (b) b.textContent = POD.playing ? '❚❚ Podcast pausieren' : ((POD.i > 0 || POD.si > 0 || POD.t > 0) ? '🎙 Podcast fortsetzen' : '🎙 Zusammenfassung Podcast');
  var c = $('podCtl'); if (!c) return;
  var seg = POD.segs[POD.i];
  c.hidden = !POD.segs.length || (!POD.playing && POD.i === 0 && POD.si === 0 && !POD.t);
  if ($('podNow')) $('podNow').textContent = seg ? 'Jetzt: ' + seg.name : '';
  if ($('podInfo')) $('podInfo').textContent = seg ? ((POD.i) + ' / ' + (POD.segs.length - 2) + ' Aktien · ' + (seg.audio ? 'Gemini-Stimme' : 'Gerätestimme')) : '';
  if ($('podPP')) $('podPP').textContent = POD.playing ? '❚❚' : '▶';
}
function podMeta() {
  if (!('mediaSession' in navigator)) return;
  var seg = POD.segs[POD.i];
  try {
    navigator.mediaSession.metadata = new MediaMetadata({ title: 'Jetzt: ' + (seg ? seg.name : ''), artist: 'Aktien-Radar Podcast', album: 'Zusammenfassung' });
    navigator.mediaSession.playbackState = POD.playing ? 'playing' : 'paused';
    navigator.mediaSession.setActionHandler('play', function () { if (!POD.playing) podPlay(); });
    navigator.mediaSession.setActionHandler('pause', function () { podPause(); });
    try { navigator.mediaSession.setActionHandler('stop', function () { podPause(); }); } catch (e) {}
    navigator.mediaSession.setActionHandler('previoustrack', function () { podJump(-1); });
    navigator.mediaSession.setActionHandler('nexttrack', function () { podJump(1); });
  } catch (e) {}
}
function podHalt() { POD.tok++; try { if (POD.el) POD.el.pause(); } catch (e) {} try { window.speechSynthesis && window.speechSynthesis.cancel(); } catch (e) {} }
function podNext() { POD.i++; POD.si = 0; POD.t = 0; if (POD.i >= POD.segs.length) { POD.playing = false; POD.i = 0; podSave(); podUI(); podMeta(); return; } podSave(); podRun(); }
function podRun() {
  var seg = POD.segs[POD.i], tok = ++POD.tok; if (!seg) return;
  podUI(); podMeta();
  if (seg.audio) {
    if (!POD.el) { POD.el = new Audio(); POD.el.preload = 'auto'; }
    var a = POD.el, src = 'data/audio/' + encodeURIComponent(seg.audio.file) + '?v=' + seg.audio.hash, last = 0;
    if (a.dataset.src !== src) { a.src = src; a.dataset.src = src; }
    var seek = function () { try { if (Math.abs(a.currentTime - POD.t) > 1) a.currentTime = POD.t; } catch (e) {} };
    a.onloadedmetadata = seek;
    a.ontimeupdate = function () { if (tok !== POD.tok) return; POD.t = a.currentTime; if (Math.abs(POD.t - last) > 2) { last = POD.t; podSave(); } };
    a.onended = function () { if (tok === POD.tok && POD.playing) podNext(); };
    a.onerror = function () { if (tok !== POD.tok) return; seg.audio = null; POD.t = 0; podRun(); };
    seek(); var pr = a.play(); if (pr && pr.catch) pr.catch(function () { if (tok !== POD.tok) return; POD.playing = false; podUI(); podMeta(); });
    return;
  }
  var ss = window.speechSynthesis; if (!ss) { POD.playing = false; podUI(); return; }
  POD.sents = splitSents(seg.text);
  if (POD.si >= POD.sents.length) { podNext(); return; }
  var u = new SpeechSynthesisUtterance(POD.sents[POD.si]), v = pickVoice();
  u.lang = v ? v.lang : 'de-DE'; if (v) u.voice = v; u.rate = 0.95;
  u.onend = function () { if (tok !== POD.tok || !POD.playing) return; POD.si++; podSave(); podRun(); };
  u.onerror = function () { if (tok !== POD.tok) return; POD.playing = false; podUI(); podMeta(); };
  ss.speak(u);
}
function podPlay() {
  if (!POD.segs.length) podBuild();
  if (P.playing) { plStopSpeech(); P.playing = false; try { plSave(); plUI(); } catch (e) {} }
  POD.playing = true; podRun();
}
function podPause() { if (!POD.playing) return; var g = POD.segs[POD.i]; if (g && g.audio && POD.el) { try { POD.t = POD.el.currentTime; } catch (e) {} } POD.playing = false; podHalt(); podSave(); podUI(); podMeta(); }
function podJump(d) {
  var was = POD.playing; podHalt();
  POD.i = Math.max(0, Math.min(POD.segs.length - 1, POD.i + d)); POD.si = 0; POD.t = 0; podSave();
  if (was) { POD.playing = true; podRun(); } else { podUI(); podMeta(); }
}
function podHtml() {
  return '<button type="button" id="podBtn" class="podBtn">🎙 Zusammenfassung Podcast</button>' +
    '<div id="podCtl" class="podCtl" hidden><div><b id="podNow"></b> <span id="podInfo" class="tiny"></span></div>' +
    '<div class="podRow"><button type="button" id="podPrev" aria-label="Vorherige Aktie">⏮</button><button type="button" id="podPP" class="primary" aria-label="Play/Pause">▶</button><button type="button" id="podNext" aria-label="Nächste Aktie">⏭</button></div></div>';
}
function bindPod() {
  if (!$('podBtn')) return;
  if (!POD.playing) { podBuild(); podRestore(); }
  $('podBtn').onclick = function () { POD.playing ? podPause() : podPlay(); };
  $('podPP').onclick = function () { POD.playing ? podPause() : podPlay(); };
  $('podPrev').onclick = function () { podJump(-1); };
  $('podNext').onclick = function () { podJump(1); };
  podUI();
}
})();
