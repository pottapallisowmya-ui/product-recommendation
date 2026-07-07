import json
import sqlite3
import os

catalog_path = 'data/catalog.json'
db_path = 'data/shop.db'
static_dir = 'frontend/static'

print("--- RUNNING VALIDATION ---")

# 1. Load catalog.json
with open(catalog_path, 'r', encoding='utf-8') as f:
    catalog = json.load(f)

# 2. Connect to database
conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row
db_products = conn.execute("SELECT * FROM products").fetchall()
conn.close()

db_map = {p['id']: p for p in db_products}

errors = 0
kidsware_count = 0

for p in catalog:
    if p.get('category', '').lower() in ['kidsware', 'kids wear', 'kidswear']:
        kidsware_count += 1
        img = p.get('image', '')
        
        # Check if the image path is local
        if not img.startswith('/static/images/kidsware_'):
            print(f"[ERROR] Catalog ID {p['id']} ({p['name']}) has non-local or incorrect image path: '{img}'")
            errors += 1
            continue
            
        # Check if the file exists on disk
        # strip leading slash and join with base static dir
        rel_path = img.lstrip('/')
        full_file_path = os.path.join(static_dir, rel_path.replace('static/', ''))
        if not os.path.exists(full_file_path):
            print(f"[ERROR] File does not exist on disk: '{full_file_path}' (referenced by Catalog ID {p['id']})")
            errors += 1
            
        # Check DB match
        db_p = db_map.get(p['id'])
        if not db_p:
            print(f"[ERROR] Product ID {p['id']} not found in Database!")
            errors += 1
        else:
            db_img = db_p['image']
            if db_img != img:
                print(f"[ERROR] Database image mismatch for Product ID {p['id']}: DB has '{db_img}', Catalog has '{img}'")
                errors += 1

print(f"\nTotal Kidsware products checked: {kidsware_count}")
if errors == 0:
    print("[SUCCESS] All Kidsware product images are properly configured and files exist on disk!")
else:
    print(f"[FAILURE] Found {errors} validation errors.")
