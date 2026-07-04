import json
import os

def isbn13_to_isbn10(isbn13: str) -> str | None:
    clean = "".join(c for c in isbn13 if c.isdigit())
    if len(clean) != 13 or not clean.startswith("978"):
        return None
    digits = clean[3:12]
    val = sum((10 - i) * int(d) for i, d in enumerate(digits))
    rem = val % 11
    chk = 11 - rem
    if chk == 10:
        chk_str = 'X'
    elif chk == 11:
        chk_str = '0'
    else:
        chk_str = str(chk)
    return digits + chk_str

catalog_path = 'data/catalog.json'

with open(catalog_path, 'r', encoding='utf-8') as f:
    catalog = json.load(f)

updated_count = 0
for p in catalog:
    if p.get('category') == 'Books':
        img_url = p.get('image', '')
        if "covers.openlibrary.org/b/isbn/" in img_url:
            isbn13 = img_url.split("isbn/")[1].split("-")[0]
            isbn10 = isbn13_to_isbn10(isbn13)
            if isbn10:
                new_url = f"https://images-na.ssl-images-amazon.com/images/P/{isbn10}.01.LZZZZZZZ.jpg"
                p['image'] = new_url
                p['images'] = [new_url]
                updated_count += 1

with open(catalog_path, 'w', encoding='utf-8') as f:
    json.dump(catalog, f, indent=2)

print(f"Successfully updated {updated_count} books in {catalog_path} with Amazon cover URLs.")
