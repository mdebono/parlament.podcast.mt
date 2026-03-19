from parlament import papi, pfeed
import sys

def run():
    leg = papi.get_leg()
    sittings = papi.get_plenary_sittings(leg)

    feed = pfeed.init_feed()
    seen_guids = set()
    for i,sitting in enumerate(list(reversed(sittings))[:100]):
        audio_url = papi.get_sitting_audio_url(sitting)
        audio_url = papi.correct_audio_url(sitting, audio_url)
        if audio_url in seen_guids:
            print(f"WARNING: Duplicate GUID for sitting {papi.get_sitting_number(sitting)}: {audio_url}", file=sys.stderr)
        seen_guids.add(audio_url)
        title = papi.get_episode_title(leg, sitting)
        if i == 1:
          title = title + '-'
        pfeed.add_item(feed,
            title = title,
            description = papi.get_episode_description(leg, sitting),
            link = papi.get_sitting_url(sitting),
            audio_url = audio_url,
            pubdate = papi.get_sitting_date(sitting),
        )
    pfeed.write_feed(feed, 'podcast.rss')