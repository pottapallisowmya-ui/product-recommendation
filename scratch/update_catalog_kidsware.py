import json

catalog_path = 'data/catalog.json'

with open(catalog_path, 'r', encoding='utf-8') as f:
    catalog = json.load(f)

updated = 0
for p in catalog:
    if p.get('category', '').lower() in ['kidsware', 'kids wear', 'kidswear']:
        name = p.get('name', '').lower()
        old_image = p.get('image')
        new_image = None
        
        if 'casual t-shirt' in name or 'casual t shirt' in name or 't-shirt' in name:
            new_image = '/static/images/kidsware_casual_tshirt.png'
        elif 'cotton sleepwear' in name or 'sleepwear' in name:
            new_image = '/static/images/kidsware_cotton_sleepwear.png'
        elif 'school uniform' in name or 'uniform' in name:
            new_image = '/static/images/kidsware_school_uniform.png'
        else:
            # Fallback (e.g. for Party Dress)
            new_image = '/static/images/kidsware_final.png'
            
        if new_image and old_image != new_image:
            p['image'] = new_image
            # Also update 'images' list if it exists
            if 'images' in p:
                p['images'] = [new_image]
            updated += 1
            print(f"Updated Product ID {p.get('id')} ({p.get('name')}) -> {new_image}")

if updated:
    with open(catalog_path, 'w', encoding='utf-8') as f:
        json.dump(catalog, f, indent=2, ensure_ascii=False)
    print(f"Successfully updated {updated} products in {catalog_path}")
else:
    print("No products needed updating.")
