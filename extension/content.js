// AskAmerica Validate — content script.
// Asks the background worker whether this page has a published validation; if so, finds each
// verbatim assertion in the page text and marks it with its verdict. Does nothing otherwise.

(() => {
  const VERDICT_COLORS = {
    "true": "#1b7f3b", "mostly true": "#4c9a2a", "partially true": "#c98a00",
    "mostly false": "#d2601a", "false": "#c0272d", "not checkable here": "#6b7280",
    "stale vintage": "#6d5bd0"
  };
  let validation = null;
  let drawn = false;
  let pop = null;

  const norm = s => s.replace(/[‘’‚]/g, "'").replace(/[“”„]/g, '"')
    .replace(/—|–/g, "-").replace(/\s+/g, " ").trim();

  // Strip the editorial wrapper a verbatim assertion often carries: leading "[W]hen", quotes,
  // a trailing attribution in parentheses.
  const core = s => norm(s).replace(/^["'\[\]\s]+|["'\s]+$/g, "").replace(/\s*\([^)]*\)\s*$/, "")
    .replace(/^\[(\w)\]/, "$1");

  function textNodes(root) {
    const out = [];
    const w = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
      acceptNode(n) {
        const p = n.parentElement;
        if (!p) return NodeFilter.FILTER_REJECT;
        const tag = p.tagName;
        if (/^(SCRIPT|STYLE|NOSCRIPT|TEXTAREA|INPUT|MARK)$/.test(tag)) return NodeFilter.FILTER_REJECT;
        if (p.closest(".aa-pop, .aa-banner")) return NodeFilter.FILTER_REJECT;
        return n.nodeValue.trim() ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT;
      }
    });
    let n;
    while ((n = w.nextNode())) out.push(n);
    return out;
  }

  // Find `needle` (normalised) inside a single text node; fall back to the first 60 characters
  // when the whole sentence does not sit in one node.
  function locate(nodes, needle) {
    const tries = [needle];
    if (needle.length > 60) tries.push(needle.slice(0, 60).replace(/\s+\S*$/, ""));
    for (const t of tries) {
      if (t.length < 12) continue;
      for (const n of nodes) {
        const hay = norm(n.nodeValue);
        const at = hay.toLowerCase().indexOf(t.toLowerCase());
        if (at < 0) continue;
        // Map the normalised offset back to the raw string by walking both.
        const raw = n.nodeValue;
        let ri = 0, ni = 0, start = -1, end = -1;
        const rawNorm = c => c.replace(/[‘’‚]/g, "'").replace(/[“”„]/g, '"').replace(/—|–/g, "-");
        let lastWasSpace = true;
        for (; ri < raw.length; ri++) {
          const c = rawNorm(raw[ri]);
          const isSpace = /\s/.test(c);
          if (isSpace && lastWasSpace) continue;
          if (ni === at) start = ri;
          if (ni === at + t.length) { end = ri; break; }
          ni++;
          lastWasSpace = isSpace;
        }
        if (start >= 0 && end < 0) end = raw.length;
        if (start >= 0) return { node: n, start, end };
      }
    }
    return null;
  }

  function mark(loc, claim, idx) {
    const r = document.createRange();
    r.setStart(loc.node, loc.start);
    r.setEnd(loc.node, loc.end);
    const m = document.createElement("mark");
    m.className = "aa-claim";
    const verdict = (claim.verdict || "").toLowerCase();
    m.style.setProperty("--aa-color", VERDICT_COLORS[verdict] || "#1a3a8a");
    m.dataset.aaIdx = String(idx);
    m.title = "AskAmerica: " + verdict;
    try { r.surroundContents(m); } catch (e) { return false; }
    m.addEventListener("mouseenter", () => showPop(m, claim));
    m.addEventListener("click", ev => { ev.preventDefault(); showPop(m, claim, true); });
    return true;
  }

  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])); }

  function showPop(anchor, claim, sticky) {
    hidePop();
    const verdict = (claim.verdict || "").toLowerCase();
    const color = VERDICT_COLORS[verdict] || "#1a3a8a";
    pop = document.createElement("div");
    pop.className = "aa-pop";
    pop.style.setProperty("--aa-color", color);
    const srcs = Array.isArray(claim.sources) ? claim.sources : [];
    pop.innerHTML =
      '<span class="aa-brand">AskAmerica</span><div class="aa-verdict">' + esc(verdict) + "</div>" +
      "<dl>" +
      (claim.article_value ? "<dt>Article says</dt><dd>" + esc(claim.article_value) + "</dd>" : "") +
      (claim.warehouse_value ? "<dt>Warehouse says</dt><dd>" + esc(claim.warehouse_value) +
        (claim.table ? " <code>" + esc(claim.table) + "</code>" : "") + "</dd>" : "") +
      (claim.independent_value ? "<dt>Independent</dt><dd>" + esc(claim.independent_value) + "</dd>" : "") +
      ((claim.article_vintage || claim.warehouse_vintage) ? "<dt>Vintage</dt><dd>" + esc(claim.article_vintage || "") + " / " + esc(claim.warehouse_vintage || "") + "</dd>" : "") +
      "</dl>" +
      (claim.reason ? '<div class="aa-reason">' + esc(claim.reason) + "</div>" : "") +
      (srcs.length ? '<ul class="aa-sources">' + srcs.map(s => {
        const t = typeof s === "string" ? s : (s.title || s.url || "");
        const u = typeof s === "string" ? "" : (s.url || "");
        return "<li>" + (u ? '<a href="' + esc(u) + '" target="_blank" rel="noopener">' + esc(t || u) + "</a>" : esc(t)) + "</li>";
      }).join("") + "</ul>" : "") +
      (claim.sql ? "<details><summary>Show SQL</summary><pre>" + esc(claim.sql) + "</pre></details>" : "") +
      (validation.report_url ? '<div class="aa-report"><a href="' + esc(validation.report_url) + '" target="_blank" rel="noopener">Open the full validation report</a></div>' : "");
    document.body.appendChild(pop);
    const rect = anchor.getBoundingClientRect();
    const top = window.scrollY + rect.bottom + 6;
    let left = window.scrollX + rect.left;
    const maxLeft = window.scrollX + document.documentElement.clientWidth - pop.offsetWidth - 12;
    if (left > maxLeft) left = Math.max(window.scrollX + 8, maxLeft);
    pop.style.top = top + "px";
    pop.style.left = left + "px";
    if (!sticky) {
      const leave = () => { setTimeout(() => { if (pop && !pop.matches(":hover") && !anchor.matches(":hover")) hidePop(); }, 250); };
      anchor.addEventListener("mouseleave", leave, { once: true });
      pop.addEventListener("mouseleave", leave);
    } else {
      const off = ev => { if (pop && !pop.contains(ev.target) && ev.target !== anchor) { hidePop(); document.removeEventListener("mousedown", off); } };
      setTimeout(() => document.addEventListener("mousedown", off), 0);
    }
  }

  function hidePop() { if (pop) { pop.remove(); pop = null; } }

  function banner(v, found, total) {
    const b = document.createElement("div");
    b.className = "aa-banner";
    const t = v.tally || {};
    const parts = Object.keys(t).map(k => t[k] + " " + k).join(" · ");
    b.innerHTML = '<strong>AskAmerica validated this page</strong><span>' + esc(parts) + "</span>" +
      (found < total ? "<span>(" + (total - found) + " claim" + (total - found === 1 ? "" : "s") + " not located on the page)</span>" : "") +
      (v.report_url ? '<a href="' + esc(v.report_url) + '" target="_blank" rel="noopener">Open report</a>' : "") +
      '<span class="aa-close" title="Hide">✕</span>';
    b.querySelector(".aa-close").addEventListener("click", () => b.remove());
    document.body.appendChild(b);
  }

  function draw() {
    if (drawn || !validation || !Array.isArray(validation.claims)) return;
    drawn = true;
    const nodes = textNodes(document.body);
    let found = 0;
    validation.claims.forEach((c, i) => {
      const needle = core(c.assertion || "");
      if (!needle) return;
      const loc = locate(nodes, needle);
      if (loc && mark(loc, c, i)) found++;
    });
    banner(validation, found, validation.claims.length);
  }

  function undraw() {
    hidePop();
    document.querySelectorAll("mark.aa-claim").forEach(m => {
      const t = document.createTextNode(m.textContent);
      m.replaceWith(t);
    });
    document.querySelectorAll(".aa-banner").forEach(b => b.remove());
    drawn = false;
  }

  chrome.runtime.onMessage.addListener((msg, _s, reply) => {
    if (msg && msg.type === "aa:redraw") {
      if (msg.on === false) undraw(); else { undraw(); draw(); }
      reply({ ok: true });
    }
    if (msg && msg.type === "aa:page-state") {
      reply({ url: location.href, drawn, found: document.querySelectorAll("mark.aa-claim").length });
    }
    return true;
  });

  chrome.runtime.sendMessage({ type: "aa:claims", url: location.href }, res => {
    if (chrome.runtime.lastError) return;
    if (res && res.status === 200 && res.body && res.body.found) {
      validation = res.body;
      chrome.storage.sync.get({ autoHighlight: true }, ({ autoHighlight }) => { if (autoHighlight) draw(); });
    }
  });
})();
