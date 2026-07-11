---
name: verify
description: Drive `python -m parlament` end-to-end in a sandbox with no access to parlament.mt or Cloudflare R2.
---

# Verifying parlament.podcast.mt changes

The runtime surface is `python -m parlament` (the daily CI job). parlament.mt
is normally unreachable from dev sandboxes (its WAF blocks anything that isn't
the curl_cffi Chrome-impersonated handshake, which agent proxies break), and
there are no R2 credentials. Both boundaries can be faked without touching the
app code:

1. **R2/S3** — run a local moto server; boto3 picks up `AWS_ENDPOINT_URL`:

   ```bash
   pip install 'moto[server]'   # may need --ignore-installed PyYAML on debian
   python -m moto.server -p 5001 &
   export AWS_ENDPOINT_URL=http://127.0.0.1:5001 AWS_ACCESS_KEY_ID=test \
          AWS_SECRET_ACCESS_KEY=test AWS_DEFAULT_REGION=us-east-1 S3_BUCKET=parlament-verify
   python -c "import boto3; boto3.client('s3').create_bucket(Bucket='parlament-verify')"
   ```

2. **parlament.mt HTTP** — pre-seed the app's own `cache.pkl` (its pickle HTTP
   cache, keyed `('GET', url)` / `('POST', payload, url)`) with canned
   `cache._CachedResponse` objects for: the media-archive page + API, the
   homepage + GetLatestMediaFiles API, and the `/mt/...` agenda pages. Seed
   UTF-8 HTML **with a `<meta charset>`** or lxml mis-decodes it.

3. **mp3 downloads** — the one thing the cache can't replay across items
   (mirror.py deletes `temp_audio.mp3` after each upload). Stub
   `cache.httpGetFile` to write a small fake file, then run the real
   entrypoint via `runpy.run_module('parlament', run_name='__main__')`.

Run from a scratch directory (`cache.pkl` and `podcast.rss` are written to the
CWD). Flows worth driving: fresh run (bootstrap catalogue), second run with
sources returning fewer items (catalogue must keep every episode in
`podcast.rss`), unexpected GetLatestMediaFiles shape (run degrades with a
warning), S3 endpoint down (run aborts, no feed written). Inspect
`podcast.rss` with lxml and `catalog/episodes.json` in the moto bucket.
