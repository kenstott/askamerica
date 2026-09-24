(async () => {
  const tab = (await chrome.tabs.query({ active: true, currentWindow: true }))[0];
  const url = tab && tab.url || "";
  document.getElementById("url").textContent = url;
  // A highlighted passage is a specific claim to check, not the whole page — when present,
  // the validate buttons send it instead of the bare URL. No `content_scripts` match on this
  // tab (e.g. a chrome:// page) leaves selection "" and falls back to page-level validation.
  let selection = "";
  if (tab && tab.id != null) {
    const selRes = await chrome.tabs.sendMessage(tab.id, { type: "aa:get-selection" }).catch(() => null);
    selection = (selRes && selRes.selection) || "";
  }
  const urlEl = document.getElementById("url");
  const newsBtn = document.getElementById("validateNews");
  if (selection) {
    urlEl.textContent = "“" + (selection.length > 140 ? selection.slice(0, 140) + "…" : selection) + "”";
    urlEl.title = "Selected text — this is what gets validated, not the whole page";
    document.getElementById("validateDesktop").textContent = "Validate this selection with AskAmerica";
    // A selected claim always overrides page-level framing, so the news-report button (which
    // only changes how the whole page is checked) has nothing to add here.
    newsBtn.hidden = true;
  }
  document.getElementById("version").textContent = "v" + chrome.runtime.getManifest().version;
  const statusEl = document.getElementById("status");
  const statusText = document.getElementById("statusText");
  const result = document.getElementById("result");
  const toggle = document.getElementById("toggle");
  let highlighted = true;

  const st = await chrome.runtime.sendMessage({ type: "aa:status" });
  if (st && st.status === 200 && st.body && st.body.ok) {
    statusEl.classList.add("ok");
    statusText.textContent = "Engine running · " + st.body.validations + " validation" + (st.body.validations === 1 ? "" : "s") + " this session";
  } else {
    statusEl.classList.add("down");
    statusText.textContent = "Engine not reachable. Open Claude Desktop with the AskAmerica connector to enable verdicts.";
  }

  if (/^https?:/i.test(url)) {
    const res = await chrome.runtime.sendMessage({ type: "aa:claims", url });
    if (res && res.status === 200 && res.body && res.body.found) {
      const v = res.body;
      const tally = v.tally || {};
      const pills = Object.keys(tally).map(k =>
        '<span class="pill" style="background:' + (AA_VERDICT_COLORS[k] || "#1a3a8a") + '">' + tally[k] + " " + k + "</span>").join("");
      const items = (v.claims || []).map(c =>
        '<li><span class="v" style="color:' + (AA_VERDICT_COLORS[(c.verdict || "").toLowerCase()] || "#1a3a8a") + '">' +
        (c.verdict || "") + "</span><br>" + (c.assertion || "").replace(/[&<>]/g, ch => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[ch])) + "</li>").join("");
      result.innerHTML = '<div class="tally">' + pills + "</div><ol class=\"claims\">" + items + "</ol>" +
        (v.report_url ? '<a href="' + v.report_url + '" target="_blank" rel="noopener">Open the full report</a>' : "");
      toggle.hidden = false;
      const state = await chrome.tabs.sendMessage(tab.id, { type: "aa:page-state" }).catch(() => null);
      highlighted = !!(state && state.drawn);
      toggle.textContent = highlighted ? "Hide highlights" : "Show highlights";
    } else {
      result.innerHTML = '<div class="hint">No validation published for this page yet.</div>';
    }
  }

  // Recent reports, last 24h (features 1-3: list, quick-open, copyable summary) — all
  // sourced from one /reports call, so only fetched once the engine is confirmed reachable
  // above; an unreachable engine or a 403 (key mismatch between this extension build and the
  // running engine build) just hides the section rather than showing an error, since this is
  // a bonus view, not the popup's main job of validating the current page. "Recent (24h)",
  // not "session" -- the engine now shares this across every open conversation via its
  // pgwire-govdata connection, so there's no single well-defined "session" to name it after.
  if (st && st.status === 200) {
    const rres = await chrome.runtime.sendMessage({ type: "aa:reports" });
    const reports = (rres && rres.status === 200 && rres.body && rres.body.reports) || [];
    if (reports.length > 0) {
      const sessionBar = document.getElementById("sessionBar");
      const sessionList = document.getElementById("sessionList");
      const sessionToggle = document.getElementById("sessionToggle");
      sessionBar.hidden = false;
      sessionToggle.textContent = "Recent reports, 24h (" + reports.length + ")";

      const esc = s => (s || "").replace(/[&<>]/g, ch => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[ch]));
      sessionList.innerHTML = reports.map(r => {
        const pills = Object.keys(r.tally || {}).map(k =>
          '<span class="pill" style="background:' + (AA_VERDICT_COLORS[k] || "#1a3a8a") + '">' + r.tally[k] + " " + esc(k) + "</span>").join("");
        return '<li><div class="title">' + esc(r.title || "(untitled)") + '</div>' +
          '<div class="tally">' + pills + '</div>' +
          '<div class="links">' +
          '<a href="' + esc(r.url) + '" target="_blank" rel="noopener">Article</a>' +
          (r.report_url ? '<a href="' + esc(r.report_url) + '" target="_blank" rel="noopener">Report</a>' : "") +
          '</div></li>';
      }).join("");

      sessionToggle.addEventListener("click", e => {
        e.preventDefault();
        sessionList.hidden = !sessionList.hidden;
        sessionToggle.textContent = (sessionList.hidden ? "Recent reports, 24h (" : "Hide recent reports (") + reports.length + ")";
      });

      document.getElementById("copySummary").addEventListener("click", async e => {
        e.preventDefault();
        const totals = {};
        for (const r of reports) {
          for (const k of Object.keys(r.tally || {})) totals[k] = (totals[k] || 0) + r.tally[k];
        }
        const totalsLine = Object.keys(totals).map(k => totals[k] + " " + k).join(", ") || "no claims graded";
        const lines = [
          "AskAmerica, last 24h: " + reports.length + " article(s) checked — " + totalsLine + ".", ""
        ];
        for (const r of reports) {
          const rTally = Object.keys(r.tally || {}).map(k => r.tally[k] + " " + k).join(", ") || "no claims graded";
          lines.push("- " + (r.title || "(untitled)") + " (" + r.url + "): " + rTally);
        }
        const copyBtn = e.target;
        try {
          await navigator.clipboard.writeText(lines.join("\n"));
          const original = copyBtn.textContent;
          copyBtn.textContent = "Copied!";
          setTimeout(() => { copyBtn.textContent = original; }, 1200);
        } catch (err) {
          // Clipboard permission denied or unavailable — nothing more useful to do than
          // leave the button's own label unchanged; the summary was still computed correctly.
        }
      });
    }
  }

  document.getElementById("validateDesktop").addEventListener("click", async () => {
    await chrome.runtime.sendMessage({ type: "aa:validate", url, selection, tabId: tab.id, target: "desktop" });
    window.close();
  });
  newsBtn.addEventListener("click", async () => {
    await chrome.runtime.sendMessage({ type: "aa:validate", url, selection, tabId: tab.id, target: "desktop", mode: "news" });
    window.close();
  });
  toggle.addEventListener("click", async () => {
    highlighted = !highlighted;
    await chrome.runtime.sendMessage({ type: "aa:highlight", tabId: tab.id, on: highlighted });
    toggle.textContent = highlighted ? "Hide highlights" : "Show highlights";
  });
  document.getElementById("options").addEventListener("click", e => { e.preventDefault(); chrome.runtime.openOptionsPage(); });
})();
