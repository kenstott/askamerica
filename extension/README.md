# AskAmerica Validate — browser extension

Validate the factual claims on the page you are reading, on your own Claude plan. The extension
runs no model of its own: it hands the page to a new Claude chat (Desktop or claude.ai) where the
AskAmerica connector does the work, then reads the published verdicts back from the engine
running on your machine and highlights each checked claim on the page.

## How it works

1. **Launch.** The toolbar icon or the right-click entry "Validate this page with AskAmerica"
   opens `claude://claude.ai/new?q=Validate this article: <url>` — Claude Desktop's own
   new-chat deep link — with the prompt staged in the composer. Press Enter. (The popup also
   offers the same on claude.ai for browsers without the Desktop app.)
2. **Validate.** The engine's validation instructions take over inside that chat: every
   assertion is extracted verbatim, tested against the warehouse, graded, and published with a
   claim-by-claim table.
3. **Overlay.** On publish, the engine records the claims table under the article's URL and
   serves it on `http://127.0.0.1:45123/claims?url=…`. The content script asks for the current
   page's table, finds each verbatim assertion in the page text, and marks it with its verdict.
   Hover or click a mark for the article figure, the warehouse figure, the independent figure,
   the sources, and the SQL. The toolbar badge shows the number of claims checked, coloured by
   the worst verdict.

Nothing leaves the machine except what your own Claude session sends; the loopback endpoint is
read-only, keyed by exact URL, and has no listing.

## Install (unpacked)

1. `chrome://extensions` → enable **Developer mode** → **Load unpacked** → choose this
   `extension/` directory.
2. Pin the AskAmerica icon from the extensions menu.
3. Run the AskAmerica engine (Claude Desktop with the connector configured). The popup shows
   "Engine running" when `http://127.0.0.1:45123/status` answers.

Edge, Brave, Arc and other Chromium browsers load the same directory. Firefox and Safari need a
manifest tweak (`browser_specific_settings`, or the Xcode converter) but the code is the same.

## Files

- `manifest.json` — MV3 manifest: action + popup, context menu, content script, options page.
- `background.js` — service worker: context menu, badge, all requests to the engine.
- `content.js` / `content.css` — locates and marks verbatim assertions; popover per claim.
- `popup.html` / `popup.js` — engine status, verdict tally, launch buttons, highlight toggle.
- `options.html` — engine port and auto-highlight setting.
- `icons/` — the AskAmerica logo rendered at 16/32/48/128 px from `web/icon.svg`.

## Engine side

`ClaimsServer` in `askamerica-engine` (fixed loopback port, `-Daskamerica.claims.port` to
change) records a validation on every `publish_report` that carries `claims`, keyed by
`source_url` (defaults to the session's last `web_fetch` URL). `GET /status` answers
`{ok, validations}`; `GET /claims?url=` answers the stored table or 404.
