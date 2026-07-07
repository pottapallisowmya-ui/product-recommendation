import json
import sqlite3
import os

catalog_path = 'data/catalog.json'
db_path = 'data/shop.db'

print("--- Catalog.json Inspection ---")
if os.path.exists(catalog_path):
    with open(catalog_path, 'r', encoding='utf-8') as f:
        catalog = json.load(f)
    for p in catalog:
        img = p.get('image', '')
        if img and not img.startswith('/static/') and not img.startswith('http'):
            print(f"Catalog ID {p.get('id')}: {p.get('name')} -> Image: '{img}'")
        elif 'kidsware' in img.lower() or 'kidswear' in img.lower():
            print(f"Catalog ID {p.get('id')} (Kidsw/ear): {p.get('name')} -> Image: '{img}'")
else:
    print("Catalog.json not found")

print("\n--- DB shop.db Inspection ---")
if os.path.exists(db_path):
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("SELECT id, name, image FROM products")
    rows = c.fetchall()
    for row in rows:
        pid, name, img = row
        if img and not img.startswith('/static/') and not img.startswith('http'):
            print(f"DB ID {pid}: {name} -> Image: '{img}'")
        elif img and ('kidsware' in img.lower() or 'kidswear' in img.lower()):
            print(f"DB ID {pid} (Kidsw/ear): {name} -> Image: '{img}'")
    conn.close()
else:
    print("shop.db not found")
