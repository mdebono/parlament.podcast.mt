from datetime import datetime
import os
import sys

from parlament import papi, latest, pfeed, mirror, catalog

# Candidates are plain dicts shared by both discovery sources
# (papi.get_plenary_candidates, latest.get_candidates):
#   source_audio_path  encoded site-relative path of the mp3 (/Audio/...)
#   kind               'plenary' | 'committee' | 'event'
#   title              episode title
#   link               absolute URL of the sitting/meeting page
#   pubdate            aware datetime
#   source             'media-archive' | 'latest-media'
#   build_description  zero-arg callable; only invoked for new episodes so
#                      agenda pages are not re-fetched on every run

ARCHIVE_SITTING_LIMIT = 20

def gather_candidates():
    """Collect candidates from both sources. Either source may fail without
    taking down the run; the catalogue still republishes everything known.
    Returns (leg, candidates); leg is None if the media-archive fetch
    itself failed (used both for plenary candidates and for backfilling)."""
    leg = None
    candidates = []
    try:
        leg = papi.get_leg()
        sittings = papi.get_plenary_sittings(leg)
        recent = list(reversed(sittings))[:ARCHIVE_SITTING_LIMIT]
        candidates += papi.get_plenary_candidates(leg, recent)
    except Exception as e:
        print(f'Warning: media-archive source failed: {e}', file=sys.stderr)

    try:
        meetings = latest.get_latest_media()
        candidates += latest.get_candidates(leg, meetings)
    except Exception as e:
        print(f'Warning: latest-media source failed: {e}', file=sys.stderr)

    return leg, candidates

def ingest(store, candidates):
    """Merge candidates into the catalogue, mirroring audio for new ones.

    Candidates arrive archive-first, so when both sources see the same
    recording the archive's canonical metadata is what gets frozen. For
    already-catalogued episodes the stored entry wins - published metadata
    never mutates, so podcast clients never see edits or re-downloads."""
    for candidate in candidates:
        key = catalog.episode_key(candidate)
        if catalog.has_episode(store, key):
            entry = store['episodes'][key]
            catalog.update_existing(entry, candidate)
            if not entry['content_length']:
                entry['content_length'] = mirror.get_r2_content_length(key)
            continue

        audio_url = papi.PARLAMENT_URL + candidate['source_audio_path']
        try:
            r2_url = mirror.mirror_audio_to_r2(audio_url, candidate['source_audio_path'])
        except Exception as e:
            # Skip: the candidate is not catalogued, so it is retried on the
            # next run. An entry must never reference audio missing from R2.
            print(f'Error mirroring {audio_url} to R2: {e}', file=sys.stderr)
            continue
        content_length = mirror.get_r2_content_length(key)
        description = candidate['build_description']()
        entry = catalog.make_entry(candidate, r2_url, content_length, description)
        catalog.add_episode(store, key, entry)

_KIND_LABELS = {'plenary': 'Seduta', 'committee': 'Laqgħa'}

def archive_sitting_index(leg):
    """Map every episode_key reachable from the media archive - across all
    CommitteeTypes, not just Plenary - to its sitting dict. The archive
    holds the full history for every committee, so this lets already
    catalogued episodes be re-matched and re-described even long after
    they've rolled off the homepage widget's 20-item window."""
    index = {}
    for committee in leg.get('Committees', []):
        for sitting in committee.get('Sittings', []):
            try:
                audio_path = papi.get_bare_audio_url(sitting)
            except Exception:
                continue
            key = catalog.episode_key({'source_audio_path': audio_path})
            index[key] = sitting
    return index

def backfill_descriptions(store, leg):
    """Rebuild the description of every catalogued episode the archive can
    still account for, using the current formatting logic. Guid, title,
    link, pubdate, kind and sources are never touched - only the
    description is refreshed. Entries the archive has no equivalent for
    (kind='event', or a committee meeting it no longer carries) are left
    untouched."""
    index = archive_sitting_index(leg)
    for key, entry in store['episodes'].items():
        label = _KIND_LABELS.get(entry['kind'])
        sitting = index.get(key)
        if label is None or sitting is None:
            continue
        description = papi.build_sitting_description(
            label,
            papi.get_sitting_title(sitting),
            papi.get_sitting_number(sitting),
            papi.get_sitting_date(sitting),
            papi.get_sitting_agenda(sitting),
        )
        catalog.update_description(entry, description)

def build_feed(store):
    feed = pfeed.init_feed()
    for entry in catalog.sorted_entries(store):
        pfeed.add_item(feed,
            title=entry['title'],
            description=entry['description'],
            link=entry['link'],
            audio_url=entry['audio_url'],
            content_length=entry['content_length'],
            pubdate=datetime.fromisoformat(entry['pubdate']),
            unique_id=entry['guid'],
        )
    return feed

def run():
    store = catalog.load_catalog()
    previous_count = len(store['episodes'])

    leg, candidates = gather_candidates()
    if not candidates and previous_count == 0:
        raise RuntimeError('no sources available and catalogue is empty; nothing to publish')

    ingest(store, candidates)

    if os.environ.get('FORCE_BACKFILL') == 'true':
        if leg is not None:
            backfill_descriptions(store, leg)
        else:
            print('Warning: cannot backfill without media-archive data', file=sys.stderr)

    # The catalogue write is the durable commit point: it happens after all
    # mirroring, so every entry has its mp3 in R2, and before the feed write,
    # so the published feed never gets ahead of the catalogue.
    catalog.save_catalog(store, previous_count)

    feed = build_feed(store)
    pfeed.write_feed(feed, 'podcast.rss')
