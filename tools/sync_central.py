#!/usr/bin/env python3
"""Fill the Directory webapp's own data store, public/data/central.json, with only the central-catalogue fields it needs.
Read-only against the central catalogue (https://cedwyn.bucklerfamily.estate/api/catalogue, read as paged list requests).
public/data/central.json is a derived cache: never edit it by hand; the central catalogue stays the single source of truth.
The Directory lists places, buildings and organisations (public/data/entities.json), not catalogue IDs, so its field set is
per entity: for every entity whose name (or the name before any bracket) appears in a catalogue record's title or holder,
the store holds those records (id, kind, title, date_display, date_sort, status, holder, page; newest first), keyed by the
entity id, plus a count. Entities with no catalogue record are left out. The entity list is read from entities.json on
every run, so an entity the directory adds is picked up with no hand-kept list. The file is rewritten only when a record
it holds changed, and a run that cannot read the whole catalogue listing leaves it as it was. Run by
.github/workflows/sync-central.yml every 6 hours. — Sion's Tab agent"""
import json, sys, time, datetime, pathlib, urllib.request
ROOT = pathlib.Path(__file__).resolve().parent.parent
API = 'https://cedwyn.bucklerfamily.estate/api/catalogue/'
FIELDS = ('id', 'kind', 'title', 'date_display', 'date_sort', 'status', 'holder', 'page')
KINDS = {'evidence', 'artifact', 'missing_record'}
OUT = ROOT / 'public' / 'data' / 'central.json'   # served at /directory/data/central.json
ents = [(e.get('id'), e.get('name')) for e in json.loads((ROOT / 'public' / 'data' / 'entities.json').read_text(encoding='utf-8')).get('entities', [])
        if e.get('id') and e.get('name')]
if not ents:
    sys.exit('no entities in public/data/entities.json; store left as it was')
def names(n):
    out = [n]
    if '(' in n: out.append(n.split('(')[0].strip())   # "Tŷ Mawr (Great House Farm)" -> also "Tŷ Mawr"
    return [x for x in dict.fromkeys(out) if len(x) >= 6]   # short names would match unrelated records
all_rows, total, off = [], None, 0
try:   # one paged listing (/api/catalogue?limit=500&offset=N, edge-cached), matched here
    while True:
        req = urllib.request.Request(f"{API.rstrip('/')}?limit=500&offset={off}", headers={'User-Agent': 'cedwyn-webapp-sync/1.1'})
        page = json.load(urllib.request.urlopen(req, timeout=60))
        rows = page.get('items') or []
        total = page.get('total', total)
        all_rows += rows
        off += len(rows)
        if not rows or (total is not None and off >= total): break
        time.sleep(1)
except Exception as e:
    sys.exit(f'catalogue listing could not be read ({e}); store left as it was')
if total is None or len({it.get('id') for it in all_rows if it.get('id')}) < total:
    sys.exit(f'catalogue listing incomplete ({len(all_rows)} of {total}); store left as it was')
by = {}
for eid, name in ents:
    recs = {}
    for nm in names(name):
        for it in all_rows:
            hay = ((it.get('title') or '') + ' ' + (it.get('holder') or '')).lower()
            if it.get('id') and it.get('kind') in KINDS and nm.lower() in hay:
                recs[it['id']] = {k: it.get(k) for k in FIELDS}
    if recs:
        rows = sorted(recs.values(), key=lambda r: (r.get('date_sort') or '', r['id']), reverse=True)
        by[eid] = {'name': name, 'count': len(rows), 'records': rows}
prev = {}
try: prev = json.loads(OUT.read_text(encoding='utf-8'))
except Exception: pass
if prev.get('entities') == by:
    print('no change', sum(v['count'] for v in by.values())); sys.exit(0)
doc = {
    'source': API.rstrip('/'),
    'note': "The Directory webapp's own data store: for each entity in public/data/entities.json that a central-catalogue record "
            'names in its title or holder, those records. Derived and read-only; never edit by hand (tools/sync_central.py rewrites it).',
    'fields': list(FIELDS),
    'match': 'entity name (also the name before any bracket; names under 6 characters skipped) found in the record title or holder',
    'synced_utc': datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
    'entities_checked': len(ents), 'count': sum(v['count'] for v in by.values()), 'entities': by}
OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
print('written', len(by), 'entities', doc['count'], 'records')
