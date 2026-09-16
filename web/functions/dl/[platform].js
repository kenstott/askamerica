// Cloudflare Pages Function: /dl/:platform
//
// Redirects to the correct installer asset in the LATEST kenstott/calcite
// release. This keeps the download links stable even though the release
// asset filenames carry version numbers — the site never needs editing when
// a new engine release ships.
//
// Routes: /dl/macos → .pkg, /dl/windows → .msi, /dl/linux → .deb,
//         /dl/browserext → askamerica-extension.zip (matched by exact name,
//         not just ".zip" — the same release also ships several Trino
//         plugin .zip archives).

const EXT_BY_PLATFORM = {
  macos: ".pkg",
  windows: ".msi",
  linux: ".deb",
};

const NAME_BY_PLATFORM = {
  browserext: "askamerica-extension.zip",
};

const RELEASES_API =
  "https://api.github.com/repos/kenstott/calcite/releases/latest";

export async function onRequest(context) {
  const platform = context.params.platform;
  const exactName = NAME_BY_PLATFORM[platform];
  const ext = EXT_BY_PLATFORM[platform];
  if (!exactName && !ext) {
    return new Response("Unknown platform", { status: 404 });
  }

  const findAsset = (release) =>
    (release.assets || []).find((a) =>
      exactName
        ? a.name.toLowerCase() === exactName.toLowerCase()
        : a.name.toLowerCase().endsWith(ext)
    );

  // A release's assets go from "none of them present" to "all of them present" over the
  // several minutes its build workflow takes -- the .msi in particular lands last, after
  // notarization. Caching the GitHub response for 5 minutes (to stay under the
  // unauthenticated 60/hr rate limit) means a request that lands during that window can get
  // a "not there yet" snapshot cached and then keep serving that same stale miss for up to 5
  // more minutes after the asset actually showed up -- exactly what got reported live,
  // 2026-09-15: the .msi had finished uploading, but /dl/windows kept 404ing well after.
  // A "found it" result is safe to cache hard (assets don't disappear once published), so
  // only the miss path needs to distrust the cache -- fetch once more bypassing it entirely
  // before actually declaring the asset absent.
  async function fetchRelease(bypassCache) {
    const res = await fetch(RELEASES_API, {
      headers: {
        "User-Agent": "askamerica-site",
        Accept: "application/vnd.github+json",
      },
      cf: bypassCache
        ? { cacheTtl: 0, cacheEverything: false }
        : { cacheTtl: 300, cacheEverything: true },
    });
    if (!res.ok) {
      throw new Error("Could not reach GitHub releases");
    }
    return res.json();
  }

  let release;
  try {
    release = await fetchRelease(false);
    if (!findAsset(release)) {
      release = await fetchRelease(true);
    }
  } catch (e) {
    return new Response("Could not reach GitHub releases", { status: 502 });
  }

  const asset = findAsset(release);
  if (!asset) {
    const label = exactName || ext;
    return new Response(`No ${label} asset in the latest release`, { status: 404 });
  }

  return Response.redirect(asset.browser_download_url, 302);
}
