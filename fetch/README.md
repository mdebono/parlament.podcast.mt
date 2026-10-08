# The parlament.mt fetch Worker

The nightly run reaches parlament.mt through this Cloudflare Worker, with a user-agent naming the podcast (`docs/decisions.md`, D1, D2).

- `worker.js` fetches one parlament.mt address per call: `GET /?u=<url>`, `&m=HEAD` (answered as JSON), `&m=POST` (no body, parlament.mt's API only), `&ref=<page>` for the Referer. It adds `x-fetch-colo` and `x-fetch-ray` to what it returns, and the app prints them at a 403 (D4) and a `colos:` line at the end of a run (D5).
- The workflows start it with `npx wrangler@4 dev --remote --port 8787 -c fetch/wrangler.jsonc` and run the app with `PARLAMENT_VIA=http://127.0.0.1:8787`. They need the repository secrets `CLOUDFLARE_API_TOKEN` and `CLOUDFLARE_ACCOUNT_ID`.
- Without `PARLAMENT_VIA`, `parlament/cache.py` asks parlament.mt directly.
