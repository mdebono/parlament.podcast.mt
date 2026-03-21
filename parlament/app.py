from curl_cffi import requests

from parlament import cache, papi, pfeed, mirror
import sys
import os

def run():
    leg = papi.get_leg()
    sittings = papi.get_plenary_sittings(leg)

    feed = pfeed.init_feed()
    seen_urls = set()
    for sitting in list(reversed(sittings))[:20]:
        s3_key = papi.get_bare_audio_url(sitting)
        if s3_key in seen_urls:
            print(f"WARNING: Duplicate URL for sitting {papi.get_sitting_number(sitting)}: {s3_key}", file=sys.stderr)
        seen_urls.add(s3_key)

        audio_url = papi.get_sitting_audio_url(sitting)

        # Mirror audio to R2 and use the R2 URL in the feed
        try:
            # TODO: s3_key is probably redundant
            r2_url = mirror.mirror_audio_to_r2(audio_url, s3_key)
        except Exception as e:
            print(f"Error mirroring {audio_url} to R2: {e}", file=sys.stderr)
            continue  # skip this item if mirroring fails
        
        pfeed.add_item(feed,
            title = papi.get_episode_title(leg, sitting),
            description = papi.get_episode_description(leg, sitting),
            link = papi.get_sitting_url(sitting),
            audio_url = r2_url,
            content_length = papi.get_audio_content_length(audio_url),
            pubdate = papi.get_sitting_date(sitting),
        )
    pfeed.write_feed(feed, 'podcast.rss')