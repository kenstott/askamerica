// Cloudflare Pages Function: /dl/:platform
//
// Redirects to the correct installer asset in the newest COMPLETE kenstott/calcite
// release. This keeps the download links stable even though the release
// asset filenames carry version numbers — the site never needs editing when
// a new engine release ships.
//
// A release is public from the moment it is created, but its assets arrive over the
// following hour (or never, if the build fails). "Complete" means it carries every
// download the site offers, so every button points at the same version and none of them
// 404s while a newer release is still building.
//
// Routes: /dl/macos → .pkg, /dl/windows → .msi, /dl/linux → .deb,
//         /dl/browserext → askamerica-extension.zip (matched by exact name,
//         not just ".zip" — the same release also ships several Trino
//         plugin .zip archives), /dl/jar → askamerica-engine.jar.

const EXT_BY_PLATFORM = {
  macos: ".pkg",
  windows: ".msi",
  linux: ".deb",
};

const NAME_BY_PLATFORM = {
  browserext: "askamerica-extension.zip",
  jar: "askamerica-engine.jar",
};

// Every download the site offers; a release lacking any of them is still being built.
const REQUIRED_EXTS = Object.values(EXT_BY_PLATFORM);
const REQUIRED_NAMES = Object.values(NAME_BY_PLATFORM);

const RELEASES_API =
  "https://api.github.com/repos/kenstott/calcite/releases?per_page=10";

const assetName = (a) => a.name.toLowerCase();

const findAsset = (release, exactName, ext) =>
  (release.assets || []).find((a) =>
    exactName ? assetName(a) === exactName.toLowerCase() : assetName(a).endsWith(ext)
  );

const isComplete = (release) =>
  !release.draft &&
  !release.prerelease &&
  REQUIRED_EXTS.every((e) => findAsset(release, null, e)) &&
  REQUIRED_NAMES.every((n) => findAsset(release, n, null));

// GitHub returns releases newest first.
const newestComplete = (releases) => releases.find(isComplete);

export async function onRequest(context) {
  const platform = context.params.platform;
  const exactName = NAME_BY_PLATFORM[platform];
  const ext = EXT_BY_PLATFORM[platform];
  if (!exactName && !ext) {
    return new Response("Unknown platform", { status: 404 });
  }

  // A release's assets go from "none of them present" to "all of them present" over the
  // several minutes its build workflow takes -- the .msi in particular lands last, after
  // notarization. Caching the GitHub response for 5 minutes (to stay under the
  // unauthenticated 60/hr rate limit) means a request that lands during that window can get
  // a "not there yet" snapshot cached and then keep serving that same stale miss for up to 5
  // more minutes after the release actually completed -- exactly what got reported live,
  // 2026-09-15: the .msi had finished uploading, but /dl/windows kept 404ing well after.
  // A "found it" result is safe to cache hard (assets don't disappear once published), so
  // only the miss path needs to distrust the cache -- fetch once more bypassing it entirely
  // before declaring that no release is complete. One list call per fetch, never one per release.
  async function fetchReleases(bypassCache) {
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
    release = newestComplete(await fetchReleases(false));
    if (!release) {
      release = newestComplete(await fetchReleases(true));
    }
  } catch (e) {
    return new Response("Could not reach GitHub releases", { status: 502 });
  }

  if (!release) {
    return new Response(
      "A new version is being published; try again in a few minutes",
      { status: 503, headers: { "Retry-After": "300" } }
    );
  }

  return Response.redirect(findAsset(release, exactName, ext).browser_download_url, 302);
}
