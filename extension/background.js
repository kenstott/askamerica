// AskAmerica Validate — service worker.
// Owns the context menu, the badge, and every request to the local engine. The content script
// and popup ask this worker for claims so that only one place holds the host permission.

const DEFAULT_PORT = 45123;
const VERDICT_COLORS = {
  "true": "#1b7f3b", "mostly true": "#4c9a2a", "partially true": "#c98a00",
  "mostly false": "#d2601a", "false": "#c0272d", "not checkable here": "#6b7280",
  "stale vintage": "#6d5bd0"
};

async function getPort() {
  const { enginePort } = await chrome.storage.sync.get({ enginePort: DEFAULT_PORT });
  return enginePort || DEFAULT_PORT;
}

async function engineFetch(path) {
  const port = await getPort();
  const ctl = new AbortController();
  const t = setTimeout(() => ctl.abort(), 1500);
  try {
    const r = await fetch("http://127.0.0.1:" + port + path, { signal: ctl.signal });
    const body = await r.json().catch(() => null);
    return { status: r.status, body };
  } catch (e) {
    return { status: 0, body: null, error: String(e) };
  } finally {
    clearTimeout(t);
  }
}

async function engineStatus() {
  return engineFetch("/status");
}

async function claimsFor(url) {
  if (!url || !/^https?:/i.test(url)) return { status: 0, body: null };
  return engineFetch("/claims?url=" + encodeURIComponent(url));
}

// A highlighted passage is a specific claim to check, not a request to validate the whole
// page it happens to sit on — selection always wins over `mode`, even for the news-report
// button, since a selected claim is a more specific ask than a page-level framing.
//
// Every prompt names the AskAmerica connector explicitly and spells out the tool sequence
// (search_catalog, then query, then publish_report) instead of just saying "validate this" and
// hoping Claude reaches for the connector on its own — a bare "Validate this article: <url>"
// is exactly as likely to get answered from general web knowledge as from the connector.
function validatePrompt(url, selection, mode) {
  if (selection && selection.trim()) {
    return "Using the AskAmerica connector, fact-check this specific claim: \"" + selection.trim()
      + "\" (from " + url + "). Check it against AskAmerica's own warehouse data first "
      + "(search_catalog, then query); if no matching table exists, verify it against "
      + "independent primary sources instead and say so. Grade it true, mostly true, partially "
      + "true, mostly false, false, not checkable here, or stale vintage, and publish the "
      + "result with publish_report.";
  }
  if (mode === "news") {
    return "Using the AskAmerica connector, fact-check this news report the way a professional "
      + "fact-checker would: " + url + ". Extract every factual claim and attributed quote in "
      + "the piece, verify each one against AskAmerica's own government data where a matching "
      + "table exists (search_catalog, then query) and against independent primary sources "
      + "otherwise. Grade the piece's overall accuracy on the Washington Post Fact Checker's "
      + "0-4 Pinocchio scale, and flag anything materially misleading even if the individual "
      + "facts check out. Publish the result with publish_report.";
  }
  return "Using the AskAmerica connector, validate every factual claim in this article: " + url
    + ". Check each claim against AskAmerica's own warehouse data first (search_catalog, then "
    + "query); grade anything with no matching table 'not checkable here' rather than skipping "
    + "it, and verify against independent primary sources where the corpus doesn't cover it. "
    + "Publish the result with publish_report.";
}

// The claude:// scheme is Claude Desktop's own registered protocol handler (its authority
// happens to be spelled "claude.ai" by Anthropic's own URI design, same as any custom
// scheme — this never touches a browser or the actual claude.ai website). Desktop-only:
// there is no browser/claude.ai fallback path.
function desktopLink(url, selection, mode) {
  return "claude://claude.ai/new?q=" + encodeURIComponent(validatePrompt(url, selection, mode))
    + "&surface=chat&source=askamerica-extension";
}

async function launchValidate(url, tabId, selection, mode) {
  const link = desktopLink(url, selection, mode);
  // Navigating the page to a custom scheme hands off to the OS handler without leaving the
  // article; Chrome asks once whether to open Claude. If no handler exists (Desktop isn't
  // installed), nothing happens — there is no fallback to fall back to.
  await chrome.tabs.update(tabId, { url: link }).catch(() => {});
}

function summarize(tally) {
  let n = 0;
  let worst = null;
  const order = ["false", "mostly false", "partially true", "stale vintage",
    "not checkable here", "mostly true", "true"];
  for (const k of Object.keys(tally || {})) n += tally[k];
  for (const k of order) if (tally && tally[k]) { worst = k; break; }
  return { n, worst };
}

async function refreshBadge(tabId, url) {
  if (!url || !/^https?:/i.test(url)) {
    await chrome.action.setBadgeText({ tabId, text: "" });
    return;
  }
  const res = await claimsFor(url);
  if (res.status === 200 && res.body && res.body.found) {
    const { n, worst } = summarize(res.body.tally);
    await chrome.action.setBadgeText({ tabId, text: String(n) });
    await chrome.action.setBadgeBackgroundColor({ tabId, color: VERDICT_COLORS[worst] || "#1a3a8a" });
    await chrome.action.setTitle({ tabId, title: "AskAmerica: " + n + " claims checked (" + worst + ")" });
  } else {
    await chrome.action.setBadgeText({ tabId, text: "" });
    await chrome.action.setTitle({ tabId, title: "Validate with AskAmerica" });
  }
}

chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.create({
    id: "aa-validate-selection",
    title: "Validate this selection with AskAmerica",
    contexts: ["selection"]
  });
  chrome.contextMenus.create({
    id: "aa-validate-page",
    title: "Validate this page with AskAmerica",
    contexts: ["page", "link"]
  });
});

chrome.contextMenus.onClicked.addListener(async (info, tab) => {
  const url = info.linkUrl || info.pageUrl || (tab && tab.url);
  if (info.menuItemId === "aa-validate-selection") {
    await launchValidate(url, tab && tab.id, info.selectionText);
    return;
  }
  if (info.menuItemId === "aa-validate-page") {
    await launchValidate(url, tab && tab.id);
  }
});

chrome.tabs.onActivated.addListener(async ({ tabId }) => {
  const tab = await chrome.tabs.get(tabId).catch(() => null);
  if (tab) refreshBadge(tabId, tab.url);
});

chrome.tabs.onUpdated.addListener((tabId, change, tab) => {
  if (change.status === "complete") refreshBadge(tabId, tab.url);
});

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  (async () => {
    switch (msg && msg.type) {
      case "aa:claims": {
        const url = msg.url || (sender.tab && sender.tab.url);
        const res = await claimsFor(url);
        if (sender.tab) refreshBadge(sender.tab.id, url);
        sendResponse(res);
        break;
      }
      case "aa:status":
        sendResponse(await engineStatus());
        break;
      case "aa:validate":
        await launchValidate(msg.url, msg.tabId, msg.selection, msg.mode);
        sendResponse({ ok: true });
        break;
      case "aa:highlight": {
        // Ask the page to (re)draw its highlights.
        if (msg.tabId) chrome.tabs.sendMessage(msg.tabId, { type: "aa:redraw", on: msg.on !== false });
        sendResponse({ ok: true });
        break;
      }
      default:
        sendResponse({ error: "unknown message" });
    }
  })();
  return true;
});
