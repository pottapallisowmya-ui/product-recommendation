import json

with open('data/catalog.json', 'r', encoding='utf-8') as f:
    catalog = json.load(f)

for p in catalog:
    if p.get('category', '').lower() in ['kidsware', 'kids wear', 'kidswear']:
        print(f"ID: {p.get('id')} | Name: {p.get('name')} | Image: {p.get('image')}")
