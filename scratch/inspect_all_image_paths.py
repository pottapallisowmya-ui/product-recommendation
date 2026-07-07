import json
from collections import Counter

with open('data/catalog.json', 'r', encoding='utf-8') as f:
    catalog = json.load(f)

prefixes = []
for p in catalog:
    img = p.get('image', '')
    if img:
        # Find prefix (e.g. before the first slash, or before the filename)
        if img.startswith('http'):
            prefixes.append('http(s)')
        else:
            prefixes.append(img.split('/')[1] if len(img.split('/')) > 1 else 'no_slash')

print("Image path prefixes count:")
print(Counter(prefixes))

print("\nAll non-http image paths (first 50):")
non_http = [p.get('image') for p in catalog if p.get('image') and not p.get('image').startswith('http')]
for i, path in enumerate(non_http[:50]):
    print(f" - {path}")
