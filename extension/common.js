// Shared helpers (loaded by popup and options; background and content inline their own copies
// because a service worker and a content script cannot import a classic script).
const AA_DEFAULT_PORT = 45123;

function aaEngineBase(port) {
  return "http://127.0.0.1:" + (port || AA_DEFAULT_PORT);
}

// Kept in sync with background.js's validatePrompt() default (article) case — see that
// file's comment for why every prompt names the AskAmerica connector explicitly.
function aaValidatePrompt(url) {
  return "Using the AskAmerica connector, validate every factual claim in this article: " + url
    + ". Check each claim against AskAmerica's own warehouse data first (search_catalog, then "
    + "query); grade anything with no matching table 'not checkable here' rather than skipping "
    + "it, and verify against independent primary sources where the corpus doesn't cover it. "
    + "Publish the result with publish_report.";
}

// Claude Desktop registers the claude:// scheme and opens a new chat with the prompt staged in
// the composer at claude://claude.ai/new?q=<text> (its authority is spelled "claude.ai" by
// Anthropic's own URI design — this never touches a browser or the claude.ai website). Not
// auto-sent: the reader presses Enter. Desktop-only, no web/browser fallback.
function aaDesktopLink(url) {
  return "claude://claude.ai/new?q=" + encodeURIComponent(aaValidatePrompt(url))
    + "&surface=chat&source=askamerica-extension";
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
