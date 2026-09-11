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
// page it happens to sit on — the two prompts are deliberately different shapes.
function validatePrompt(url, selection) {
  if (selection && selection.trim()) {
    return "Validate this claim: \"" + selection.trim() + "\" (from " + url + ")";
  }
  return "Validate this article: " + url;
}

function desktopLink(url, selection) {
  return "claude://claude.ai/new?q=" + encodeURIComponent(validatePrompt(url, selection))
    + "&surface=chat&source=askamerica-extension";
}

function webLink(url, selection) {
  return "https://claude.ai/new?q=" + encodeURIComponent(validatePrompt(url, selection));
}

async function launchValidate(url, tabId, target, selection) {
  const link = target === "web" ? webLink(url, selection) : desktopLink(url, selection);
  if (target === "web") {
    await chrome.tabs.create({ url: link });
    return;
  }
  // Navigating the page to a custom scheme hands off to the OS handler without leaving the
  // article; Chrome asks once whether to open Claude. If no handler exists nothing happens,
  // so the popup also offers the web link.
  try {
    await chrome.tabs.update(tabId, { url: link });
  } catch (e) {
    await chrome.tabs.create({ url: webLink(url, selection) });
  }
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
    await launchValidate(url, tab && tab.id, "desktop", info.selectionText);
    return;
  }
  if (info.menuItemId === "aa-validate-page") {
    await launchValidate(url, tab && tab.id, "desktop");
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
        await launchValidate(msg.url, msg.tabId, msg.target || "desktop", msg.selection);
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
