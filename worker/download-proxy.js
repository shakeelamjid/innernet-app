/**
 * Innernet download proxy — a Cloudflare Worker.
 *
 * Serves the current APK from https://dl.<your-domain>/ while GitHub actually
 * stores and serves the bytes. The customer never sees the publishing account,
 * and the file still comes off Cloudflare's edge rather than a single VPS, so
 * it stays fast and costs the server nothing.
 *
 * Why a proxy and not a redirect: a redirect cannot hide its destination — the
 * browser has to connect to that host, and the address ends up in the download
 * manager. Only proxying keeps it out of sight.
 *
 * It relies on the build publishing a stable-named asset ("Innernet.apk")
 * alongside the versioned one, so there is no GitHub API call here — nothing to
 * rate-limit, and nothing to change when a new build goes out.
 */

const REPO = "shakeelamjid/innernet-app";   // <-- change if the repo moves
const ASSET = "Innernet.apk";               // stable name published by the workflow
const SOURCE = `https://github.com/${REPO}/releases/latest/download/${ASSET}`;

export default {
  async fetch(request) {
    if (request.method !== "GET" && request.method !== "HEAD") {
      return new Response("Method not allowed", { status: 405 });
    }

    // Forward Range so a dropped download can resume — phones on poor
    // connections rely on this, and a 32 MB file drops often.
    const range = request.headers.get("Range");

    let upstream;
    try {
      upstream = await fetch(SOURCE, {
        method: request.method,
        headers: range ? { Range: range } : {},
        redirect: "follow",
        cf: { cacheEverything: true, cacheTtl: 3600 },
      });
    } catch (e) {
      return notReady();
    }

    if (!upstream.ok && upstream.status !== 206) return notReady();

    // Build the response headers from scratch. Copying the upstream set would
    // pass through "server: GitHub.com" and x-github-* — which would give away
    // exactly what this exists to hide.
    const headers = new Headers();
    headers.set("Content-Type", "application/vnd.android.package-archive");
    headers.set("Content-Disposition", `attachment; filename="${ASSET}"`);
    headers.set("Cache-Control", "public, max-age=1800");
    headers.set("Accept-Ranges", "bytes");
    for (const h of ["Content-Length", "Content-Range", "ETag", "Last-Modified"]) {
      const v = upstream.headers.get(h);
      if (v) headers.set(h, v);
    }

    return new Response(request.method === "HEAD" ? null : upstream.body, {
      status: upstream.status,
      headers,
    });
  },
};

function notReady() {
  return new Response(
    "The download is being prepared. Please try again in a minute.",
    {
      status: 503,
      headers: {
        "Content-Type": "text/plain; charset=utf-8",
        "Cache-Control": "no-store",
      },
    }
  );
}
