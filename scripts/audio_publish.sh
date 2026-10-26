#!/usr/bin/env bash
# Branch "audio" = nur aktuelle MP3s (Startseite data/audio/*.mp3 + Entdecken data/audio/ent/*.mp3), per jsDelivr ausgeliefert.
set -e
python3 - > "$RUNNER_TEMP/keep.txt" <<'P'
import json, os
fs = []
try:
    i = json.load(open('data/audio/index.json'))
    fs += ['data/audio/' + x['file'] for x in i.get('stocks', {}).values()] + ['data/audio/' + x['file'] for x in (i.get('extra') or {}).values()]
except Exception: pass
try:
    e = json.load(open('data/audio/ent/index.json'))
    fs += ['data/audio/ent/' + f for f in e.get('files', {})] + ['data/audio/ent/index.json']
except Exception: pass
print('\n'.join(p for p in fs if os.path.exists(p)))
P
export GIT_INDEX_FILE="$RUNNER_TEMP/aidx"
git read-tree --empty
xargs -a "$RUNNER_TEMP/keep.txt" git update-index --add
tree=$(git write-tree)
unset GIT_INDEX_FILE
old=$(git rev-parse -q --verify refs/remotes/origin/audio || true)
if [ -n "$old" ] && [ "$(git rev-parse "$old^{tree}")" = "$tree" ]; then sha=$old; else
  sha=$(git -c user.name=aktien-radar-bot -c user.email=actions@users.noreply.github.com commit-tree "$tree" -m "Audio $(date -u +%FT%TZ)")
  git push -f -q origin "$sha:refs/heads/audio"
fi
python3 - "$sha" <<'P'
import json, sys
base = 'https://cdn.jsdelivr.net/gh/ayoub971-prog/aktien-radar@%s/data/audio/' % sys.argv[1]
for p, k in (('data/audio/index.json', 'base'), ('data/podcast.json', 'audio_base'), ('data/entdecken.json', 'audio_base')):
    try: i = json.load(open(p))
    except Exception: continue
    i[k] = base; json.dump(i, open(p, 'w'), ensure_ascii=False, indent=1 if p.endswith('index.json') else 0)
P
echo "Audio-Branch: $sha ($(wc -l < "$RUNNER_TEMP/keep.txt") Dateien)"
