import json
import sqlite3
import os

static_images_dir = 'static/images'
files_in_images = os.listdir(static_images_dir)

with open('data/catalog.json', 'r', encoding='utf-8') as f:
    catalog = json.load(f)

print("Checking Catalog.json:")
for p in catalog:
    img = p.get('image', '')
    for f in files_in_images:
        if f in img or os.path.splitext(f)[0] in img:
            print(f"Match in Catalog: Product ID {p.get('id')} ({p.get('name')}) has image '{img}' which matches '{f}'")

print("\nChecking DB shop.db:")
db_path = 'data/shop.db'
if os.path.exists(db_path):
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("SELECT id, name, image FROM products")
    rows = c.fetchall()
    for row in rows:
        pid, name, img = row
        for f in files_in_images:
            if img and (f in img or os.path.splitext(f)[0] in img):
                print(f"Match in DB: Product ID {pid} ({name}) has image '{img}' which matches '{f}'")
    conn.close()
