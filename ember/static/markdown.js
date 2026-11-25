/* Ember markdown: small, safe renderer. All text is HTML-escaped first;
   only a fixed set of tags is produced. No raw HTML from the model is ever used. */
(function () {
  "use strict";
  var MAX_LINES = 20000;
  var LANG_ALIAS = { arduino: "cpp", ino: "cpp", "c++": "cpp", h: "c", sh: "bash", shell: "bash", zsh: "bash",
    py: "python", js: "javascript", ts: "typescript", yml: "yaml", conf: "ini", platformio: "ini", console: "bash" };

  function esc(s) {
    return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }

  function inlineText(s) {
    var t = esc(s);
    t = t.replace(/\*\*([^*\n]+)\*\*/g, "<strong>$1</strong>");
    t = t.replace(/__([^_\n]+)__/g, "<strong>$1</strong>");
    t = t.replace(/(^|[\s(])\*([^*\s][^*\n]*)\*/g, "$1<em>$2</em>");
    t = t.replace(/\[([^\]\n]{1,200})\]\((https?:\/\/[^\s)"']{1,500})\)/g,
      '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
    t = t.replace(/\[(\d{1,2})\]/g, '<a class="cite" data-cite="$1" href="#">$1</a>');
    return t;
  }

  function inline(s) {
    var parts = String(s).split("`");
    var out = "";
    for (var i = 0; i < parts.length; i++) {
      if (i % 2 === 1 && i < parts.length - 1) out += "<code>" + esc(parts[i]) + "</code>";
      else if (i % 2 === 1) out += esc("`") + inlineText(parts[i]);
      else out += inlineText(parts[i]);
    }
    return out;
  }

  function codeBlock(lang, code, highlight) {
    var name = (lang || "").toLowerCase();
    var hl = LANG_ALIAS[name] || name;
    var body = esc(code);
    if (highlight && window.hljs) {
      try {
        if (hl && window.hljs.getLanguage(hl)) body = window.hljs.highlight(code, { language: hl, ignoreIllegals: true }).value;
      } catch (e) { console.warn("highlight failed", e); body = esc(code); }
    }
    return '<div class="codeblock"><div class="codehead"><span>' + esc(name || "code") +
      '</span><button type="button" data-copy-code>Copy</button></div><pre><code class="hljs">' + body + "</code></pre></div>";
  }

  function splitRow(line) {
    var s = line.trim();
    if (s.charAt(0) === "|") s = s.slice(1);
    if (s.charAt(s.length - 1) === "|") s = s.slice(0, -1);
    return s.split("|");
  }

  function table(rows) {
    var head = splitRow(rows[0]);
    var html = "<table><thead><tr>";
    for (var i = 0; i < head.length && i < 20; i++) html += "<th>" + inline(head[i].trim()) + "</th>";
    html += "</tr></thead><tbody>";
    for (var r = 2; r < rows.length; r++) {
      var cells = splitRow(rows[r]);
      html += "<tr>";
      for (var c = 0; c < cells.length && c < 20; c++) html += "<td>" + inline(cells[c].trim()) + "</td>";
      html += "</tr>";
    }
    return html + "</tbody></table>";
  }

  var RE_FENCE = /^\s*```\s*([\w+#.-]*)\s*$/;
  var RE_HEAD = /^(#{1,4})\s+(.*)$/;
  var RE_HR = /^\s*([-*_])(\s*\1){2,}\s*$/;
  var RE_QUOTE = /^\s*>\s?(.*)$/;
  var RE_UL = /^\s*[-*+]\s+(.*)$/;
  var RE_OL = /^\s*\d{1,4}[.)]\s+(.*)$/;
  var RE_TSEP = /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/;

  function render(text, opts) {
    var highlight = !!(opts && opts.highlight);
    var lines = String(text || "").replace(/\r\n?/g, "\n").split("\n");
    if (lines.length > MAX_LINES) lines = lines.slice(0, MAX_LINES);
    var out = [], para = [], i = 0, m;
    function flush() { if (para.length) { out.push("<p>" + para.join("<br>") + "</p>"); para = []; } }
    while (i < lines.length) {
      var line = lines[i];
      if ((m = RE_FENCE.exec(line))) {
        flush();
        var lang = m[1], code = [];
        i++;
        while (i < lines.length && !/^\s*```\s*$/.test(lines[i])) { code.push(lines[i]); i++; }
        out.push(codeBlock(lang, code.join("\n"), highlight));
        i++;
        continue;
      }
      if (line.indexOf("|") !== -1 && i + 1 < lines.length && RE_TSEP.test(lines[i + 1])) {
        flush();
        var rows = [];
        while (i < lines.length && lines[i].indexOf("|") !== -1) { rows.push(lines[i]); i++; }
        out.push(table(rows));
        continue;
      }
      if ((m = RE_HEAD.exec(line))) { flush(); out.push("<h" + m[1].length + ">" + inline(m[2]) + "</h" + m[1].length + ">"); i++; continue; }
      if (RE_HR.test(line)) { flush(); out.push("<hr>"); i++; continue; }
      if (RE_QUOTE.test(line)) {
        flush();
        var q = [];
        while (i < lines.length && (m = RE_QUOTE.exec(lines[i]))) { q.push(inline(m[1])); i++; }
        out.push("<blockquote>" + q.join("<br>") + "</blockquote>");
        continue;
      }
      if (RE_UL.test(line) || RE_OL.test(line)) {
        flush();
        var ordered = !RE_UL.test(line), re = ordered ? RE_OL : RE_UL, items = [];
        while (i < lines.length && (m = re.exec(lines[i]))) { items.push("<li>" + inline(m[1]) + "</li>"); i++; }
        var tag = ordered ? "ol" : "ul";
        out.push("<" + tag + ">" + items.join("") + "</" + tag + ">");
        continue;
      }
      if (!line.trim()) { flush(); i++; continue; }
      para.push(inline(line));
      i++;
    }
    flush();
    return out.join("\n");
  }

  window.EmberMD = { render: render, escape: esc };
})();
