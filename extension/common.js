// Shared helpers (loaded by popup and options; background and content inline their own copies
// because a service worker and a content script cannot import a classic script).
const AA_DEFAULT_PORT = 45123;

function aaEngineBase(port) {
  return "http://127.0.0.1:" + (port || AA_DEFAULT_PORT);
}

function aaValidatePrompt(url) {
  return "Validate this article: " + url;
}

// Claude Desktop registers the claude:// scheme and opens a new chat with the prompt staged in
// the composer at claude://claude.ai/new?q=<text>. The web app accepts the same query on
// https://claude.ai/new. Neither auto-sends: the reader presses Enter.
function aaDesktopLink(url) {
  return "claude://claude.ai/new?q=" + encodeURIComponent(aaValidatePrompt(url))
    + "&surface=chat&source=askamerica-extension";
}

function aaWebLink(url) {
  return "https://claude.ai/new?q=" + encodeURIComponent(aaValidatePrompt(url));
}

const AA_VERDICT_COLORS = {
  "true": "#1b7f3b",
  "mostly true": "#4c9a2a",
  "partially true": "#c98a00",
  "mostly false": "#d2601a",
  "false": "#c0272d",
  "not checkable here": "#6b7280",
  "stale vintage": "#6d5bd0"
};
