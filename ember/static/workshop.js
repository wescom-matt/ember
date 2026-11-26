/* Ember Workshop: Radio (CHIRP), Printer (CC2), Parts library, Hosts. Plain JS, same-origin API only. */
(function () {
  "use strict";
  var U = window.EmberUI, $ = function (id) { return document.getElementById(id); };
  var el = U.el, api = U.api;
  var ws = { radioHosts: [], radios: [], models: [], targets: [], lastGcode: "" };

  function msg(t) { $("ws-msg").textContent = t || ""; }
  function btn(label, fn, cls) { var b = el("button", "btn small" + (cls ? " " + cls : ""), label); b.type = "button"; b.addEventListener("click", fn); return b; }
  function opt(sel, value, label) { var o = el("option", "", label); o.value = String(value); sel.appendChild(o); }
  function run(p) { msg("Working…"); return p.then(function (r) { msg(""); return r; }, function (e) { msg(e.message); throw e; }); }
  function hostSelect(id, role) {
    var sel = $(id); sel.textContent = ""; opt(sel, 0, "active " + role + " host");
    ws.targets.filter(function (t) { return (t.roles || "").split(",").indexOf(role) >= 0; })
      .forEach(function (t) { opt(sel, t.id, t.name); });
  }

  function showTab(name) {
    document.querySelectorAll(".wtab").forEach(function (t) { t.classList.toggle("active", t.dataset.wtab === name); });
    ["radio", "printer", "parts", "hosts"].forEach(function (n) { $("wtab-" + n).classList.toggle("hidden", n !== name); });
    msg("");
    var f = { radio: loadRadio, printer: loadPrinter, parts: searchParts, hosts: loadHosts }[name];
    f().catch(function (e) { msg(e.message); });
  }

  async function loadTargets() { var d = await api("GET", "/api/targets"); ws.targets = d.targets || []; ws.active = d.active || {}; return d; }

  /* ---------- radio ---------- */
  async function loadRadio() {
    await loadTargets();
    var d = await api("GET", "/api/radio");
    ws.models = d.models; ws.radios = d.radios;
    hostSelect("rd-host", "radio");
    var ms = $("rd-model"); ms.textContent = "";
    d.models.forEach(function (m) { opt(ms, m.key, m.label + (m.mode === "none" ? " (not in CHIRP)" : "")); });
    $("rd-helper").textContent = d.helper ? "" : "CHIRP helper not installed on the P1 yet (channel lists need it).";
    var box = $("rd-list"); box.textContent = "";
    if (!d.radios.length) box.appendChild(el("p", "muted", "No radios yet. Add one below."));
    d.radios.forEach(function (r) { box.appendChild(radioCard(r)); });
  }

  function radioCard(r) {
    var card = el("div", "act");
    var head = el("div", "act-head");
    head.appendChild(el("strong", "", r.name));
    head.appendChild(el("span", "act-target", r.model + (r.port ? " · " + r.port : "")));
    head.appendChild(el("span", "spacer"));
    if (r.mode !== "none") head.appendChild(btn(r.mode === "live" ? "Read channels" : "Read radio (backup)", function () { backup(r); }, "primary"));
    card.appendChild(head);
    var model = ws.models.filter(function (m) { return m.key === r.model_key; })[0];
    if (model) card.appendChild(el("div", "act-why", model.note));
    r.images.slice(0, 8).forEach(function (i) {
      var row = el("div", "img-row");
      row.appendChild(el("span", "tag " + i.kind, i.kind));
      row.appendChild(el("span", "muted", new Date(i.created_at * 1000).toLocaleString() + " · " + i.sha256.slice(0, 10) + (i.note ? " · " + i.note : "")));
      row.appendChild(btn("Open", function () { openImage(r, i); }));
      card.appendChild(row);
    });
    return card;
  }

  async function backup(r) {
    var port = $("rd-port-pick").value || r.port;
    await run(api("POST", "/api/radio/radios/" + r.id + "/backup", { host_id: Number($("rd-host").value) || 0, port: port }));
    await loadRadio();
  }

  async function openImage(r, img) {
    var d = await run(api("GET", "/api/radio/images/" + img.id + "/channels"));
    var pane = $("rd-detail"); pane.textContent = "";
    pane.appendChild(el("h3", "", r.name + " · image #" + img.id + " (" + img.kind + ")"));
    if (d.text) { pane.appendChild(el("pre", "", d.text)); return; }
    if (d.diff && d.diff.length) pane.appendChild(diffTable(d.diff));
    var t = el("table", "users chan");
    var hr = el("tr"); ["#", "Name", "Freq", "Duplex", "Offset", "Tone", "rTone", "Mode", "Power"].forEach(function (h) { hr.appendChild(el("th", "", h)); });
    t.appendChild(hr);
    d.channels.forEach(function (c) {
      var tr = el("tr");
      [c.number, c.name, c.freq.toFixed(4), c.duplex, c.offset ? c.offset.toFixed(3) : "", c.tmode, c.tmode ? c.rtone : "", c.mode, c.power].forEach(function (v) { tr.appendChild(el("td", "", String(v))); });
      t.appendChild(tr);
    });
    pane.appendChild(t);
    if (r.mode === "clone") pane.appendChild(editForm(r, img));
  }

  function diffTable(diff) {
    var box = el("div", "diffbox");
    box.appendChild(el("strong", "", diff.length + " channel change(s) vs the image it came from"));
    diff.forEach(function (x) {
      var line = x.change === "changed"
        ? "#" + x.number + " changed: " + Object.keys(x.fields).map(function (f) { return f + " " + x.fields[f][0] + " → " + x.fields[f][1]; }).join(", ")
        : "#" + x.number + " " + x.change + (x.after ? ": " + x.after.name + " " + x.after.freq : "");
      box.appendChild(el("div", "d-" + x.change, line));
    });
    return box;
  }

  function editForm(r, img) {
    var f = el("form", "add-user");
    var fields = [["number", "ch #", "4rem"], ["name", "name", "7rem"], ["freq", "MHz", "7rem"], ["duplex", "+ / - / blank", "6rem"],
      ["offset", "offset MHz", "6rem"], ["tmode", "Tone/TSQL/blank", "8rem"], ["rtone", "tone Hz", "5rem"]];
    var inputs = {};
    f.appendChild(el("strong", "", "Edit a channel (makes a new image; nothing is sent to the radio):"));
    fields.forEach(function (x) { var i = el("input"); i.placeholder = x[1]; i.style.width = x[2]; inputs[x[0]] = i; f.appendChild(i); });
    var del = el("label", "toggle"); var cb = el("input"); cb.type = "checkbox"; del.appendChild(cb); del.appendChild(el("span", "", "Clear channel")); f.appendChild(del);
    f.appendChild(btn("Make edited image", async function () {
      var e = { number: Number(inputs.number.value) };
      if (cb.checked) e.empty = true;
      else Object.keys(inputs).forEach(function (k) { if (k !== "number" && inputs[k].value !== "") e[k] = inputs[k].value; });
      var res = await run(api("POST", "/api/radio/images/" + img.id + "/edit", { edits: [e] }));
      var pane = $("rd-detail"); pane.textContent = "";
      pane.appendChild(el("h3", "", "New image #" + res.id + " — review the changes"));
      pane.appendChild(diffTable(res.diff));
      pane.appendChild(btn("Upload to radio…", function () { upload(r, res.id, res.diff.length); }, "danger"));
    }, "primary"));
    return f;
  }

  async function upload(r, imageId, n) {
    var port = $("rd-port-pick").value || r.port;
    if (!window.confirm("Write image #" + imageId + " (" + n + " change(s)) to " + r.name + " on " + (port || "its port") + "?\n\nEmber reads a fresh backup from the radio first. Keep the radio on and the cable still.")) return;
    var d = await run(api("POST", "/api/radio/images/" + imageId + "/upload", { host_id: Number($("rd-host").value) || 0, port: port, confirm: true }));
    msg("Uploaded. Backup taken first: image #" + (d.backup && d.backup.id));
    await loadRadio();
  }

  async function findPorts() {
    var d = await run(api("POST", "/api/radio/ports", { host_id: Number($("rd-host").value) || 0 }));
    var sel = $("rd-port-pick"); sel.textContent = ""; opt(sel, "", d.ports.length ? "port on " + d.host : "no ports found on " + d.host);
    d.ports.forEach(function (p) { opt(sel, p, p); });
  }

  async function addRadio(ev) {
    ev.preventDefault();
    await run(api("POST", "/api/radio/radios", { name: $("rd-name").value.trim(), model_key: $("rd-model").value, port: $("rd-port").value.trim(), notes: "" }));
    $("add-radio").reset(); await loadRadio();
  }

  /* ---------- printer ---------- */
  async function loadPrinter() {
    await loadTargets();
    hostSelect("pr-printer", "printer"); hostSelect("pr-build", "build");
  }
  function prBody(extra) { var b = { target_id: Number($("pr-printer").value) || 0 }; Object.keys(extra || {}).forEach(function (k) { b[k] = extra[k]; }); return b; }
  async function prStatus() {
    var d = await run(api("POST", "/api/printer/status", prBody()));
    var s = d.result, box = $("pr-status"); box.textContent = "";
    [["State", s.state], ["File", s.file || "—"], ["Progress", (s.progress || 0) + "% · layer " + s.layer], ["Left", s.remaining_min + " min"], ["Nozzle", s.nozzle], ["Bed", s.bed]].forEach(function (kv) {
      var row = el("div", "kv"); row.appendChild(el("span", "muted", kv[0])); row.appendChild(el("strong", "", String(kv[1]))); box.appendChild(row);
    });
    if (s.errors && s.errors.length) box.appendChild(el("div", "error", "Printer errors: " + JSON.stringify(s.errors)));
  }
  async function prAction(action) {
    var needs = { start: 1, resume: 1, cancel: 1 }[action];
    var file = action === "start" ? ($("pr-file").value.trim() || ws.lastGcode.split(/[\/\\]/).pop()) : "";
    if (needs && !window.confirm((action === "start" ? "Start printing " + file : action.charAt(0).toUpperCase() + action.slice(1) + " the print") + " on the printer?\nCheck the bed is clear and the right filament is loaded.")) return;
    await run(api("POST", "/api/printer/" + action, prBody({ file: file, confirm: !!needs })));
    await prStatus();
  }
  async function prSlice(model, buildId) {
    var d = await run(api("POST", "/api/printer-slice", { build_host_id: buildId, model: model, nozzle: $("pr-nozzle").value, process: $("pr-process").value.trim(), filament: $("pr-filament").value.trim() }));
    sliced(d, buildId);
  }
  function sliced(d, buildId) {
    ws.lastGcode = d.gcode; ws.lastBuild = buildId;
    $("pr-gcode").textContent = "Sliced on " + d.host + ": " + d.gcode;
    $("pr-send").classList.remove("hidden");
  }
  async function prSend() {
    var name = ws.lastGcode.split(/[\/\\]/).slice(-3).join("-").replace(/[^A-Za-z0-9._-]/g, "_");
    if (!name.toLowerCase().endsWith(".gcode")) name += ".gcode";
    if (!window.confirm("Send " + ws.lastGcode + " to the printer as " + name + "? (It will not start yet.)")) return;
    await run(api("POST", "/api/printer-upload", prBody({ build_host_id: ws.lastBuild || 0, path: ws.lastGcode, file: name, confirm: true })));
    $("pr-file").value = name; msg("Sent. Press Start print when ready.");
  }

  /* ---------- parts ---------- */
  async function searchParts() {
    await loadTargets(); hostSelect("pt-build", "build");
    var d = await api("GET", "/api/parts?q=" + encodeURIComponent($("pt-q").value.trim()));
    var st = d.stats;
    $("pt-stats").textContent = st.parts + " parts · " + st.guides + " guides · " + Math.round(st.bytes / 1e6) + " MB";
    var box = $("pt-list"); box.textContent = "";
    d.results.forEach(function (h) { box.appendChild(h.kind === "part" ? partCard(h) : guideCard(h)); });
    if (!d.results.length) box.appendChild(el("p", "muted", "Nothing found."));
  }
  function partCard(p) {
    var c = el("div", "act");
    var head = el("div", "act-head");
    head.appendChild(el("strong", "", p.name)); head.appendChild(el("span", "act-target", p.category)); head.appendChild(el("span", "spacer"));
    head.appendChild(el("span", "tag", p.license)); c.appendChild(head);
    c.appendChild(el("div", "act-why", (p.notes || "") + " — by " + (p.author || "unknown") + " · " + p.source_url));
    p.files.slice(0, 30).forEach(function (f) {
      var row = el("div", "img-row");
      var a = el("a", "", f.name + " (" + Math.round(f.size / 1024) + " KB)"); a.href = "/api/parts/" + p.id + "/files/" + encodeURIComponent(f.name); a.setAttribute("download", f.name);
      row.appendChild(a);
      if (!/\.scad$/i.test(f.name)) row.appendChild(btn("Slice for CC2", async function () {
        var bid = Number($("pt-build").value) || 0;
        var d = await run(api("POST", "/api/parts/" + p.id + "/slice", { file: f.name, build_host_id: bid, nozzle: $("pt-nozzle").value }));
        showTab("printer"); sliced(d, bid); msg("Sliced. Check it, then Send to printer.");
      }));
      c.appendChild(row);
    });
    return c;
  }
  function guideCard(g) {
    var c = el("div", "act");
    var head = el("div", "act-head"); head.appendChild(el("strong", "", g.title)); head.appendChild(el("span", "spacer")); head.appendChild(el("span", "tag", g.license));
    c.appendChild(head); c.appendChild(el("div", "act-why", g.body.slice(0, 300) + "… — " + g.author + " · " + g.source_url));
    return c;
  }

  /* ---------- hosts ---------- */
  async function loadHosts() {
    await loadTargets();
    var conv = U.currentChat();
    var chat = conv ? (await api("GET", "/api/conversations/" + conv + "/hosts")).hosts : {};
    var box = $("hs-body"); box.textContent = "";
    ["radio", "build", "printer"].forEach(function (role) {
      var tr = el("tr"); tr.appendChild(el("td", "", role));
      var g = el("select"); opt(g, 0, "first available");
      var c = el("select"); opt(c, 0, "use the default");
      ws.targets.filter(function (t) { return (t.roles || "").split(",").indexOf(role) >= 0; }).forEach(function (t) { opt(g, t.id, t.name); opt(c, t.id, t.name); });
      g.value = String(ws.active[role] || 0); c.value = String(chat[role] || 0); c.disabled = !conv; g.disabled = !U.isAdmin();
      g.addEventListener("change", function () { run(api("PUT", "/api/admin/active-host", { role: role, target_id: Number(g.value) })); });
      c.addEventListener("change", function () { run(api("PUT", "/api/conversations/" + conv + "/hosts", { role: role, target_id: Number(c.value) })); });
      var t1 = el("td"); t1.appendChild(g); var t2 = el("td"); t2.appendChild(c); tr.appendChild(t1); tr.appendChild(t2); box.appendChild(tr);
    });
  }

  function wire() {
    $("ws-btn").addEventListener("click", function () { $("ws-dlg").showModal(); showTab("radio"); });
    document.querySelectorAll(".wtab").forEach(function (t) { t.addEventListener("click", function () { showTab(t.dataset.wtab); }); });
    $("rd-ports").addEventListener("click", function () { findPorts().catch(function () {}); });
    $("add-radio").addEventListener("submit", function (ev) { addRadio(ev).catch(function () {}); });
    $("pr-status-btn").addEventListener("click", function () { prStatus().catch(function () {}); });
    ["pause", "resume", "cancel", "start"].forEach(function (a) { $("pr-" + a).addEventListener("click", function () { prAction(a).catch(function () {}); }); });
    $("pr-slice").addEventListener("click", function () { prSlice($("pr-model").value.trim(), Number($("pr-build").value) || 0).catch(function () {}); });
    $("pr-send").addEventListener("click", function () { prSend().catch(function () {}); });
    $("pt-search").addEventListener("submit", function (ev) { ev.preventDefault(); searchParts().catch(function (e) { msg(e.message); }); });
  }
  wire();
  window.EmberWorkshop = { open: function (tab) { $("ws-dlg").showModal(); showTab(tab); } };
})();
