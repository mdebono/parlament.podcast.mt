from curl_cffi import requests

from parlament import cache, papi, pfeed, mirror
import sys
import os

def run():
    leg = papi.get_leg()
    sittings = papi.get_plenary_sittings(leg)

    feed = pfeed.init_feed()
    seen_guids = set()
    for sitting in list(reversed(sittings))[:10]:
        audio_url = papi.get_sitting_audio_url(sitting)
        if audio_url in seen_guids:
            print(f"WARNING: Duplicate GUID for sitting {papi.get_sitting_number(sitting)}: {audio_url}", file=sys.stderr)
        seen_guids.add(audio_url)

        # Mirror audio to R2 and use the R2 URL in the feed
        r2_key = os.path.basename(audio_url)
        try:
            r2_url = mirror.mirror_audio_to_r2(audio_url, r2_key)
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