import json, glob, os

files = sorted(glob.glob('framework/results/runs/*midterm*.json'))
f = files[-1]
print('reading', os.path.basename(f))
d = json.load(open(f))
print('top keys:', list(d.keys()))
print('series length (dates):', len(d.get('dates', [])))
print('entries:', sum(1 for v in d.get('entries', []) if v))
print('exits:', sum(1 for v in d.get('exits', []) if v))
print('--- indicators ---')
for i in d.get('indicators', []):
    vals = i.get('values', [])
    nz = sum(1 for v in vals if v is not None)
    print(f"  name={i.get('name'):10} pane={i.get('pane'):8} paneId={i.get('paneId'):7} "
          f"len={len(vals)} nonNull={nz}")
