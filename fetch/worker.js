// The parlament.mt fetch Worker (fetch/README.md): one parlament.mt address per call, with our own user-agent.
//   GET /?u=<https://parlament.mt/...>[&ref=<page>]  -> the body as fetched (status, content type and length passed through;
//                                                       headers x-fetch-colo, the Worker's colo, and x-fetch-ray, parlament.mt's cf-ray)
//   GET /?u=<…/umbraco/Api/…>&m=POST&ref=<page>     -> the API's answer (a POST without a body)
//   GET /?u=<…>&m=HEAD                              -> JSON: url (after redirects), status, content length and type
// If a KEY secret is set, every call must carry the header "x-fetch-key" equal to it.
const UA = "Il-Podcast tal-Parlament/1.0 https://parlament.podcast.mt";
const HOST = "parlament.mt";

const isHost = (h) => h === HOST || h === "www." + HOST;

export default {
  async fetch(req, env) {
    if (env.KEY && req.headers.get("x-fetch-key") !== env.KEY) return new Response("forbidden", { status: 403 });
    const q = new URL(req.url).searchParams;
    let u;
    try { u = new URL(q.get("u") || ""); } catch (_) { return new Response("?u= must be a parlament.mt address", { status: 400 }); }
    if (u.protocol !== "https:" || !isHost(u.hostname)) return new Response("parlament.mt only", { status: 400 });
    const m = q.get("m") || "GET";
    if (!["GET", "HEAD", "POST"].includes(m)) return new Response("m= must be GET, HEAD or POST", { status: 400 });
    if (m === "POST" && !u.pathname.startsWith("/umbraco/Api/")) return new Response("POST only to parlament.mt's API", { status: 400 });
    const headers = { "User-Agent": UA, "Accept-Language": "mt,en" };
    const ref = q.get("ref");
    if (ref) {
      try { if (isHost(new URL(ref).hostname)) headers["Referer"] = ref; } catch (_) { /* ignored */ }
    }
    if (m === "POST") headers["Accept"] = "application/json";
    const r = await fetch(u.toString(), { method: m, headers, redirect: "follow" });
    if (m === "HEAD") return Response.json({ url: r.url || u.toString(), status: r.status,
                                              bytes: Number(r.headers.get("content-length")) || null,
                                              type: r.headers.get("content-type"), cf_ray: r.headers.get("cf-ray"),
                                              colo: (req.cf || {}).colo });
    const out = { "content-type": r.headers.get("content-type") || "",
                  "x-fetch-colo": (req.cf || {}).colo || "", "x-fetch-ray": r.headers.get("cf-ray") || "" };
    const len = r.headers.get("content-length");
    if (len) out["content-length"] = len;
    return new Response(r.body, { status: r.status, headers: out });
  },
};
