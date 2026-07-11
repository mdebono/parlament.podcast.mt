# Persistent episode catalogue
#
# The homepage "Latest Media Files" widget and the media-archive API both
# only expose recent items, so episodes are accumulated in a JSON catalogue
# stored in the R2 bucket. Once an item is catalogued it stays in the feed
# forever, even after it rolls off the source pages. Entries carry everything
# needed to regenerate a feed item, so rolled-off episodes never require the
# origin site again.

from datetime import datetime, timezone

from parlament import mirror

CATALOG_KEY = 'catalog/episodes.json'
CATALOG_BACKUP_KEY = CATALOG_KEY + '.bak'
CATALOG_VERSION = 1

def new_catalog():
    return {'version': CATALOG_VERSION, 'episodes': {}}

def load_catalog():
    """Load the catalogue from R2, or a fresh one if none exists yet.

    Any error other than a missing object propagates: treating a transient
    read failure as an empty catalogue would silently rebuild history from
    only the items currently on the source pages."""
    try:
        return mirror.get_json(CATALOG_KEY)
    except mirror.ObjectNotFound:
        print('No catalogue found at {}; starting a new one'.format(CATALOG_KEY))
        return new_catalog()

def save_catalog(catalog, previous_count):
    """Write the catalogue back to R2, backing up the previous version.

    previous_count is the episode count at load time: the catalogue only
    ever grows, so a smaller count means a bug upstream and the write is
    refused rather than wiping history."""
    count = len(catalog['episodes'])
    if count < previous_count:
        raise RuntimeError(
            'refusing to save catalogue: shrank from {} to {} episodes'.format(
                previous_count, count))
    if previous_count > 0:
        mirror.copy_object(CATALOG_KEY, CATALOG_BACKUP_KEY)
    mirror.put_json(CATALOG_KEY, catalog)

def episode_key(candidate):
    """Catalogue/dedup key for a candidate: the R2 object key of its audio.

    Unquoting collapses the %20-vs-space encoding differences between the
    two source APIs, so the same recording maps to the same key no matter
    which source produced it."""
    return mirror.prep_s3_key(candidate['source_audio_path'])

def has_episode(catalog, key):
    return key in catalog['episodes']

def make_entry(candidate, audio_url, content_length, description, first_seen=None):
    if first_seen is None:
        first_seen = datetime.now(timezone.utc)
    return {
        # guid is stored explicitly (even though today it equals audio_url)
        # so already-published episodes keep their id under any future URL
        # scheme change - podcast clients must never see a new guid.
        'guid': audio_url,
        'title': candidate['title'],
        'description': description,
        'link': candidate['link'],
        'audio_url': audio_url,
        'content_length': content_length,
        'pubdate': candidate['pubdate'].isoformat(),
        'kind': candidate['kind'],
        'sources': [candidate['source']],
        'source_audio_path': candidate['source_audio_path'],
        'first_seen': first_seen.isoformat(),
    }

def add_episode(catalog, key, entry):
    catalog['episodes'][key] = entry

def update_existing(entry, candidate):
    """Merge a candidate into its already-catalogued entry: published
    metadata (guid, title, description, pubdate, link) never mutates, only
    the source list is unioned."""
    if candidate['source'] not in entry['sources']:
        entry['sources'].append(candidate['source'])

def update_description(entry, description):
    """Overwrite a catalogued entry's description in place (used by
    backfilling). Every other field - guid, title, link, pubdate, kind,
    sources - is left untouched; those identify the episode to already
    subscribed clients and must never change."""
    entry['description'] = description

def sorted_entries(catalog):
    """All entries, newest first (key as deterministic tiebreak)."""
    items = sorted(catalog['episodes'].items(),
                   key=lambda kv: (kv[1]['pubdate'], kv[0]),
                   reverse=True)
    return [entry for _, entry in items]
