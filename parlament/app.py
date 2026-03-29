from parlament import papi, pfeed, mirror
import sys

def run():
    leg = papi.get_leg()
    sittings = papi.get_plenary_sittings(leg)

    feed = pfeed.init_feed()
    seen_urls = set()
    for sitting in list(reversed(sittings))[:20]:
        try:
            s3_key = papi.get_bare_audio_url(sitting)
        except Exception as e:
            print(f"Warning: skipping sitting {papi.get_sitting_number(sitting)}: {e}", file=sys.stderr)
            continue
        if s3_key in seen_urls:
            print(f"WARNING: Duplicate URL for sitting {papi.get_sitting_number(sitting)}: {s3_key}", file=sys.stderr)
            continue
        seen_urls.add(s3_key)

        audio_url = papi.PARLAMENT_URL + s3_key

        # Mirror audio to R2 and use the R2 URL in the feed
        try:
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