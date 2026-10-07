# Decisions

Each decision gets the next D-number: the decision, its status and date, and the reasons. Update the docs it affects in the same change.

**D1. parlament.mt is reached through a Cloudflare fetch Worker, with our own user-agent.** _Accepted, 6 Oct 2026._
- **Why:** it is more reliable from GitHub's runners, and every request says who is asking.
- **How:** `fetch/worker.js`, started by the workflows as a preview (nothing deployed), with `PARLAMENT_VIA` pointing the app at it (`fetch/README.md`). `parlament/cache.py` uses plain `requests`, waits 2 s between requests, and stops a run's requests at the first 403.

**D2. The fetch Worker runs on the route `cf.podcast.mt/*`, so its requests name the project's domain.** _Accepted, 6 Oct 2026._
- **Why:** Cloudflare marks each request a Worker makes with the domain it runs on; the route makes that `podcast.mt`.
- **How:** the `routes` entry in `fetch/wrangler.jsonc`, on a DNS record that serves nothing.

**D3. Every Pages run re-enables its own workflow, so the nightly schedule keeps running.** _Accepted, 7 Oct 2026._
- **Why:** GitHub turns off scheduled workflows in a public repository after 60 days without activity, and the nightly run never commits.
- **How:** the last step of `pages.yml` calls the API's "enable workflow", which resets the count; the workflow's token has `actions: write` for it.

