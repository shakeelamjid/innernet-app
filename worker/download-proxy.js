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
 *
 * The caching is the whole point, and it has to be done by hand. GitHub answers
 * that stable name with two redirects and then a SIGNED url carrying a unique
 * signature and expiry. Cloudflare's automatic caching keys on the url it
 * finally fetches, so every download looked new and nothing was ever cached —
 * which made this slower than no proxy at all. Caching under a key of our own,
 * the address the customer asked for, is what makes it fast: one visitor pays
 * the redirect chain, everyone else is served from the edge.
 */

const REPO = "shakeelamjid/innernet-app";   // <-- change if the repo moves
const ASSET = "Innernet.apk";               // stable name published by the workflow
const SOURCE = `https://github.com/${REPO}/releases/latest/download/${ASSET}`;

export default {
  async fetch(request, env, ctx) {
    if (request.method !== "GET" && request.method !== "HEAD") {
      return new Response("Method not allowed", { status: 405 });
    }

    const url = new URL(request.url);
    const cache = caches.default;
    // A key of our own, stable across releases. The TTL below is what picks up
    // a new build, so it is deliberately short.
    const cacheKey = new Request(url.origin + "/Innernet.apk", { method: "GET" });

    // Range requests are for resuming a dropped download. They skip the cache:
    // a partial response must never be stored as if it were the whole file.
    const range = request.headers.get("Range");

    if (!range) {
      const hit = await cache.match(cacheKey);
      if (hit) {
        const h = new Headers(hit.headers);
        h.set("X-Innernet-Cache", "hit");
        return new Response(request.method === "HEAD" ? null : hit.body,
                            { status: hit.status, headers: h });
      }
    }

    let upstream;
    try {
      upstream = await fetch(SOURCE, {
        method: "GET",
        headers: range ? { Range: range } : {},
        redirect: "follow",
      });
    } catch (e) {
      return notReady();
    }
    if (!upstream.ok && upstream.status !== 206) return notReady();

    // Built from scratch: copying upstream would pass through "server: GitHub.com"
    // and x-github-*, giving away exactly what this exists to hide.
    const headers = new Headers();
    headers.set("Content-Type", "application/vnd.android.package-archive");
    headers.set("Content-Disposition", `attachment; filename="${ASSET}"`);
    headers.set("Accept-Ranges", "bytes");
    headers.set("X-Innernet-Cache", "miss");
    // Short enough that a new build reaches people quickly, long enough that one
    // slow origin fetch serves everybody in between.
    headers.set("Cache-Control", "public, max-age=900");
    for (const h of ["Content-Length", "Content-Range", "ETag", "Last-Modified"]) {
      const v = upstream.headers.get(h);
      if (v) headers.set(h, v);
    }

    const resp = new Response(upstream.body, { status: upstream.status, headers });

    if (!range && upstream.status === 200) {
      // clone() tees the stream, so storing it does not delay the download in
      // front of the customer who happened to arrive first.
      ctx.waitUntil(cache.put(cacheKey, resp.clone()));
    }

    return request.method === "HEAD"
      ? new Response(null, { status: resp.status, headers })
      : resp;
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
