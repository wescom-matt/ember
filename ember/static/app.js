/* Ember front end. Plain JS, no framework, no network calls except to this server. */
(function () {
  "use strict";
  var $ = function (id) { return document.getElementById(id); };
  var MD = window.EmberMD;
  var RENDER_MS = 120;
  var MAX_STREAM_EVENTS = 200000;
  var CHIPS = [
    "Write an ESP32 LoRa sender for an SX1276 that sends a temperature reading every 5 minutes",
    "How do I treat a second-degree burn with no doctor available?",
    "Explain LoRa spreading factor vs range and battery life",
    "Write a Python script that logs a serial port to a CSV file"
  ];
  var state = { me: null, models: [], defaultModel: "", kbs: [], chats: [], current: null, abort: null, searchTimer: 0 };

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined && text !== null) n.textContent = text;
    return n;
  }

  async function api(method, path, body) {
    if (window.EMBER_DEMO) return window.EMBER_DEMO.api(method, path, body);
    var opts = { method: method, headers: { "X-Ember": "1" }, credentials: "same-origin" };
    if (body !== undefined) { opts.headers["Content-Type"] = "application/json"; opts.body = JSON.stringify(body); }
    var res = await fetch(path, opts);
    var data = null;
    try { data = await res.json(); } catch (e) { data = null; }
    if (res.status === 401 && path !== "/api/login") { showLogin(); throw new Error("sign in required"); }
    if (!res.ok) throw new Error((data && typeof data.detail === "string") ? data.detail : "request failed (" + res.status + ")");
    return data;
  }

  /* ---------- views ---------- */
  function showLogin() {
    state.me = null;
    $("app-view").classList.add("hidden");
    $("login-view").classList.remove("hidden");
    $("login-user").focus();
  }

  async function showApp(me) {
    state.me = me;
    $("login-view").classList.add("hidden");
    $("app-view").classList.remove("hidden");
    $("me-name").textContent = me.username;
    $("admin-btn").classList.toggle("hidden", !me.is_admin);
    await Promise.all([loadModels(), loadKbs(), loadChats()]);
    newChat();
  }

  async function loadModels() {
    try {
      var d = await api("GET", "/api/models");
      state.models = d.models; state.defaultModel = d.default;
    } catch (e) { state.models = []; state.defaultModel = ""; notice("Ollama is not responding: " + e.message); }
    var sel = $("model-select");
    sel.textContent = "";
    state.models.forEach(function (m) {
      var o = el("option", "", m.name.replace(/:latest$/, "") + (m.name === state.defaultModel ? " (default)" : ""));
      o.value = m.name; sel.appendChild(o);
    });
    sel.value = state.defaultModel;
  }

  async function loadKbs() {
    var d = await api("GET", "/api/kbs");
    state.kbs = d.kbs;
    var sel = $("kb-select");
    sel.textContent = "";
    d.kbs.forEach(function (k) { var o = el("option", "", k.label); o.value = k.id; o.title = k.description; sel.appendChild(o); });
    sel.value = d.default;
    state.defaultKb = d.default;
  }

  async function loadChats() {
    var q = $("chat-search").value.trim();
    var d = await api("GET", "/api/conversations" + (q ? "?q=" + encodeURIComponent(q) : ""));
    state.chats = d.conversations;
    renderChatList();
  }

  function renderChatList() {
    var list = $("chat-list");
    list.textContent = "";
    list.appendChild(el("div", "list-label", $("chat-search").value.trim() ? "Search results" : "Recent"));
    if (!state.chats.length) list.appendChild(el("div", "list-label", "No chats yet"));
    state.chats.forEach(function (c) {
      var row = el("div", "chat-item" + (state.current === c.id ? " active" : ""));
      row.appendChild(el("span", "t", c.title));
      var acts = el("span", "acts");
      var ren = el("button", "", "Rename"); ren.type = "button"; ren.title = "Rename";
      var del = el("button", "", "Delete"); del.type = "button"; del.title = "Delete";
      acts.appendChild(ren); acts.appendChild(del); row.appendChild(acts);
      row.addEventListener("click", function () { openChat(c.id); });
      ren.addEventListener("click", function (ev) { ev.stopPropagation(); renameChat(c); });
      del.addEventListener("click", function (ev) { ev.stopPropagation(); deleteChat(c); });
      list.appendChild(row);
    });
  }

  function newChat() {
    if (state.abort) return;
    state.current = null;
    $("messages").textContent = "";
    $("empty").classList.remove("hidden");
    $("chat-title").textContent = "New chat";
    $("model-select").value = state.defaultModel;
    $("kb-select").value = state.defaultKb || "none";
    renderChatList();
    closeSidebar();
    $("input").focus();
  }

  async function openChat(id) {
    if (state.abort) return;
    var d = await api("GET", "/api/conversations/" + id);
    state.current = id;
    $("chat-title").textContent = d.conversation.title;
    if (state.models.some(function (m) { return m.name === d.conversation.model; })) $("model-select").value = d.conversation.model;
    $("kb-select").value = d.conversation.kb;
    var box = $("messages");
    box.textContent = "";
    $("empty").classList.toggle("hidden", d.messages.length > 0);
    d.messages.forEach(function (m) {
      if (m.role === "user") addUser(m.content);
      else finishAssistant(addAssistant(), m.content, m.thinking, m.sources, m.model);
    });
    renderChatList();
    closeSidebar();
    scrollDown(true);
  }

  async function renameChat(c) {
    var t = window.prompt("Rename chat", c.title);
    if (t === null || !t.trim()) return;
    await api("PATCH", "/api/conversations/" + c.id, { title: t.trim().slice(0, 120) });
    if (state.current === c.id) $("chat-title").textContent = t.trim();
    await loadChats();
  }

  async function deleteChat(c) {
    if (!window.confirm("Delete \"" + c.title + "\"? This cannot be undone.")) return;
    await api("DELETE", "/api/conversations/" + c.id);
    if (state.current === c.id) newChat();
    await loadChats();
  }

  /* ---------- messages ---------- */
  function scrollDown(force) {
    var s = $("scroller");
    if (force || s.scrollHeight - s.scrollTop - s.clientHeight < 160) s.scrollTop = s.scrollHeight;
  }

  function notice(text, parent) {
    var n = el("div", "notice", text);
    (parent || $("messages")).appendChild(n);
  }

  function addUser(text) {
    var row = el("div", "msg user");
    row.appendChild(el("div", "bubble", text));
    $("messages").appendChild(row);
  }

  function addAssistant() {
    var row = el("div", "msg assistant");
    var a = { row: row, status: el("div", "status"), thoughts: null, body: el("div", "body"), extra: el("div", ""), text: "", think: "", sources: [] };
    row.appendChild(a.status); row.appendChild(a.body); row.appendChild(a.extra);
    $("messages").appendChild(row);
    return a;
  }

  function setThinking(a, text) {
    if (!text) return;
    if (!a.thoughts) {
      a.thoughts = el("details", "thoughts");
      a.thoughts.appendChild(el("summary", "", "Thoughts"));
      a.thoughts.appendChild(el("div", ""));
      a.row.insertBefore(a.thoughts, a.body);
    }
    a.thoughts.lastChild.textContent = text;
  }

  function renderSources(a, sources) {
    if (!sources || !sources.length) return;
    var d = el("details", "sources");
    d.appendChild(el("summary", "", "Sources (" + sources.length + ")"));
    sources.forEach(function (s) {
      var c = el("div", "src");
      c.dataset.rank = String(s.rank);
      c.appendChild(el("div", "h", "[" + s.rank + "] " + s.title));
      c.appendChild(el("div", "m", s.source + (s.section && s.section !== s.title ? " · " + s.section : "") + " · score " + Number(s.score).toFixed(3)));
      c.appendChild(el("div", "x", s.text));
      d.appendChild(c);
    });
    a.extra.appendChild(d);
  }

  function finishAssistant(a, text, thinking, sources, model) {
    a.status.remove();
    setThinking(a, thinking);
    a.body.innerHTML = MD.render(text, { highlight: true });
    renderSources(a, sources);
    var foot = el("div", "msg-foot");
    var copy = el("button", "", "Copy"); copy.type = "button";
    copy.addEventListener("click", function () { copyText(text, copy); });
    foot.appendChild(copy);
    if (model) foot.appendChild(el("span", "", model.replace(/:latest$/, "")));
    a.extra.insertBefore(foot, a.extra.firstChild);
  }

  function copyText(text, btn) {
    var done = function () { var o = btn.textContent; btn.textContent = "Copied"; setTimeout(function () { btn.textContent = o; }, 1200); };
    if (navigator.clipboard && window.isSecureContext) {
      navigator.clipboard.writeText(text).then(done, function (e) { console.warn("copy failed", e); });
      return;
    }
    var ta = el("textarea"); ta.value = text; document.body.appendChild(ta); ta.select();
    try { document.execCommand("copy"); done(); } catch (e) { console.warn("copy failed", e); }
    ta.remove();
  }

  /* ---------- sending ---------- */
  async function ensureChat() {
    if (state.current) return state.current;
    var c = await api("POST", "/api/conversations", { model: $("model-select").value, kb: $("kb-select").value });
    state.current = c.id;
    return c.id;
  }

  function handleEvent(a, ev) {
    if (ev.type === "status") a.status.textContent = ev.text;
    else if (ev.type === "token") { a.text += ev.t; a.status.textContent = ""; }
    else if (ev.type === "think") { a.think += ev.t; }
    else if (ev.type === "sources") a.sources = ev.sources || [];
    else if (ev.type === "notice") notice(ev.text, a.extra);
    else if (ev.type === "error") notice(ev.message, a.extra);
  }

  async function readStream(res, a) {
    var reader = res.body.getReader(), dec = new TextDecoder(), buf = "", last = 0;
    for (var n = 0; n < MAX_STREAM_EVENTS; n++) {
      var r = await reader.read();
      if (r.done) break;
      buf += dec.decode(r.value, { stream: true });
      var lines = buf.split("\n");
      buf = lines.pop();
      lines.forEach(function (line) { if (line.trim()) handleEvent(a, JSON.parse(line)); });
      var t = Date.now();
      if (t - last > RENDER_MS) {
        last = t;
        setThinking(a, a.think);
        a.body.innerHTML = MD.render(a.text, { highlight: false });
        scrollDown(false);
      }
    }
  }

  async function streamReply(id, text) {
    if (window.EMBER_DEMO) return;
    var a = addAssistant();
    a.status.textContent = "Starting…";
    state.abort = new AbortController();
    setSending(true);
    var model = $("model-select").value;
    try {
      var res = await fetch("/api/conversations/" + id + "/messages", {
        method: "POST", credentials: "same-origin", signal: state.abort.signal,
        headers: { "Content-Type": "application/json", "X-Ember": "1" },
        body: JSON.stringify({ content: text, model: model, kb: $("kb-select").value, think: $("think-toggle").checked })
      });
      if (!res.ok) { var d = await res.json().catch(function () { return {}; }); throw new Error(d.detail || ("error " + res.status)); }
      await readStream(res, a);
    } catch (e) {
      if (e.name !== "AbortError") notice(e.message, a.extra); else notice("Stopped.", a.extra);
    } finally {
      finishAssistant(a, a.text || (a.think ? "" : "_(no reply)_"), a.think, a.sources, model);
      state.abort = null;
      setSending(false);
      scrollDown(false);
      loadChats().catch(function (e) { console.warn(e); });
    }
  }

  async function send(ev) {
    if (ev) ev.preventDefault();
    if (state.abort) { state.abort.abort(); return; }
    var input = $("input"), text = input.value.trim();
    if (!text) return;
    if (!$("model-select").value) { notice("No model available. Is Ollama running?"); return; }
    try {
      var id = await ensureChat();
      input.value = ""; autosize();
      $("empty").classList.add("hidden");
      addUser(text);
      scrollDown(true);
      if (state.chats.every(function (c) { return c.id !== id; })) $("chat-title").textContent = text.slice(0, 60);
      await streamReply(id, text);
    } catch (e) { notice(e.message); }
  }

  function setSending(on) {
    var b = $("send-btn");
    b.classList.toggle("stop", on);
    b.title = on ? "Stop" : "Send (Enter)";
    b.querySelector("use").setAttribute("href", on ? "#i-stop" : "#i-up");
  }

  function autosize() {
    var t = $("input");
    t.style.height = "auto";
    t.style.height = Math.min(t.scrollHeight, 220) + "px";
  }

  /* ---------- admin ---------- */
  function adminMsg(t) { $("admin-msg").textContent = t; }

  async function loadUsers() {
    var d = await api("GET", "/api/admin/users");
    var body = $("users-body");
    body.textContent = "";
    d.users.forEach(function (u) { body.appendChild(userRow(u)); });
  }

  function userRow(u) {
    var tr = el("tr");
    tr.appendChild(el("td", "", u.username + (state.me && u.id === state.me.id ? " (you)" : "")));
    ["is_admin", "is_active"].forEach(function (field) {
      var td = el("td"), cb = el("input");
      cb.type = "checkbox"; cb.checked = !!u[field];
      cb.addEventListener("change", function () { patchUser(u, field, cb); });
      td.appendChild(cb); tr.appendChild(td);
    });
    var td = el("td"), pw = el("input"), set = el("button", "btn small", "Set password");
    pw.type = "password"; pw.placeholder = "new password"; pw.minLength = 10; pw.maxLength = 256; pw.autocomplete = "new-password";
    pw.className = "hidden";
    set.type = "button";
    set.addEventListener("click", function () {
      if (pw.classList.contains("hidden")) { pw.classList.remove("hidden"); pw.focus(); return; }
      resetPassword(u, pw);
    });
    td.appendChild(pw); td.appendChild(set); tr.appendChild(td);
    return tr;
  }

  async function patchUser(u, field, cb) {
    var body = {}; body[field] = cb.checked;
    try { await api("PATCH", "/api/admin/users/" + u.id, body); adminMsg("Saved " + u.username + "."); }
    catch (e) { cb.checked = !cb.checked; adminMsg(e.message); }
  }

  async function resetPassword(u, input) {
    try {
      await api("PATCH", "/api/admin/users/" + u.id, { password: input.value });
      input.value = ""; input.classList.add("hidden");
      adminMsg("Password set for " + u.username + ". Their other sessions were signed out.");
      if (state.me && u.id === state.me.id) showLogin();
    } catch (e) { adminMsg(e.message); }
  }

  async function addUserSubmit(ev) {
    ev.preventDefault();
    try {
      await api("POST", "/api/admin/users", { username: $("nu-name").value.trim(), password: $("nu-pass").value, is_admin: $("nu-admin").checked });
      adminMsg("Added " + $("nu-name").value.trim() + ".");
      $("add-user").reset();
      await loadUsers();
    } catch (e) { adminMsg(e.message); }
  }

  async function changePassword(ev) {
    ev.preventDefault();
    try {
      await api("POST", "/api/me/password", { current: $("pw-cur").value, new: $("pw-new").value });
      $("pw-form").reset();
      $("pw-dlg").close();
      showLogin();
      $("login-error").textContent = "Password changed. Sign in again.";
    } catch (e) { $("pw-msg").textContent = e.message; }
  }

  /* ---------- login ---------- */
  async function login(ev) {
    ev.preventDefault();
    $("login-error").textContent = "";
    try {
      var me = await api("POST", "/api/login", { username: $("login-user").value.trim(), password: $("login-pass").value });
      $("login-pass").value = "";
      var full = await api("GET", "/api/me");
      await showApp(full || me);
    } catch (e) { $("login-error").textContent = e.message; }
  }

  async function logout() {
    try { await api("POST", "/api/logout"); } catch (e) { console.warn(e); }
    showLogin();
  }

  /* ---------- wiring ---------- */
  function openSidebar() { $("sidebar").classList.add("open"); $("scrim").classList.remove("hidden"); }
  function closeSidebar() { $("sidebar").classList.remove("open"); $("scrim").classList.add("hidden"); }

  function onCiteClick(ev) {
    var cite = ev.target.closest(".cite");
    if (cite) {
      ev.preventDefault();
      var msg = cite.closest(".msg"), det = msg && msg.querySelector(".sources");
      if (!det) return;
      det.open = true;
      var card = det.querySelector('.src[data-rank="' + cite.dataset.cite + '"]');
      if (card) card.scrollIntoView({ block: "nearest" });
      return;
    }
    var btn = ev.target.closest("[data-copy-code]");
    if (btn) copyText(btn.closest(".codeblock").querySelector("code").textContent, btn);
  }

  function wire() {
    $("login-form").addEventListener("submit", login);
    $("logout-btn").addEventListener("click", logout);
    $("new-chat").addEventListener("click", newChat);
    $("composer").addEventListener("submit", send);
    $("input").addEventListener("input", autosize);
    $("input").addEventListener("keydown", function (ev) {
      if (ev.key === "Enter" && !ev.shiftKey && !ev.isComposing) { ev.preventDefault(); send(); }
    });
    $("chat-search").addEventListener("input", function () {
      clearTimeout(state.searchTimer);
      state.searchTimer = setTimeout(function () { loadChats().catch(function (e) { console.warn(e); }); }, 250);
    });
    $("messages").addEventListener("click", onCiteClick);
    $("menu-btn").addEventListener("click", openSidebar);
    $("scrim").addEventListener("click", closeSidebar);
    $("admin-btn").addEventListener("click", function () { adminMsg(""); $("admin-dlg").showModal(); loadUsers().catch(function (e) { adminMsg(e.message); }); });
    $("pw-btn").addEventListener("click", function () { $("pw-msg").textContent = ""; $("pw-dlg").showModal(); });
    $("add-user").addEventListener("submit", addUserSubmit);
    $("pw-form").addEventListener("submit", changePassword);
    document.querySelectorAll("[data-close]").forEach(function (b) { b.addEventListener("click", function () { b.closest("dialog").close(); }); });
    CHIPS.forEach(function (c) {
      var b = el("button", "chip", c.length > 48 ? c.slice(0, 46) + "…" : c);
      b.type = "button"; b.title = c;
      b.addEventListener("click", function () { $("input").value = c; autosize(); $("input").focus(); });
      $("chips").appendChild(b);
    });
  }

  async function boot() {
    wire();
    api("GET", "/api/version").then(function (d) { $("version").textContent = "v" + d.version; }, function (e) { console.warn(e); });
    try {
      var me = await api("GET", "/api/me");
      await showApp(me);
    } catch (e) {
      if (state.me === null) showLogin();
    }
  }

  async function demoStart() {
    var d = window.EMBER_DEMO;
    if (!d) return;
    if (d.view === "login") { showLogin(); return; }
    if (d.open) await openChat(d.open);
    if (d.view === "admin") $("admin-btn").click();
  }

  boot().then(demoStart, function (e) { console.warn(e); });
})();
