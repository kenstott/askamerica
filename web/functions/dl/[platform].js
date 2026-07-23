// Cloudflare Pages Function: /dl/:platform
//
// Redirects to the correct installer asset in the LATEST kenstott/calcite
// release, resolved by file extension. This keeps the download links stable
// even though the release asset filenames carry version numbers — the site
// never needs editing when a new engine release ships.
//
// Routes: /dl/macos → .pkg, /dl/windows → .msi, /dl/linux → .deb

const EXT_BY_PLATFORM = {
  macos: ".pkg",
  windows: ".msi",
  linux: ".deb",
};

const RELEASES_API =
  "https://api.github.com/repos/kenstott/calcite/releases/latest";

export async function onRequest(context) {
  const ext = EXT_BY_PLATFORM[context.params.platform];
  if (!ext) {
    return new Response("Unknown platform", { status: 404 });
  }

  let release;
  try {
    const res = await fetch(RELEASES_API, {
      headers: {
        "User-Agent": "askamerica-site",
        Accept: "application/vnd.github+json",
      },
      // Cache the release metadata at the edge to stay well under GitHub's
      // unauthenticated API rate limit (60/hr/IP).
      cf: { cacheTtl: 300, cacheEverything: true },
    });
    if (!res.ok) {
      return new Response("Could not reach GitHub releases", { status: 502 });
    }
    release = await res.json();
  } catch (e) {
    return new Response("Could not reach GitHub releases", { status: 502 });
  }

  const asset = (release.assets || []).find((a) =>
    a.name.toLowerCase().endsWith(ext)
  );
  if (!asset) {
    return new Response(`No ${ext} asset in the latest release`, { status: 404 });
  }

  return Response.redirect(asset.browser_download_url, 302);
}
