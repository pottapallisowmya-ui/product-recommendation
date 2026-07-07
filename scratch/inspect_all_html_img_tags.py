import os
import re

html_files = []
for root, dirs, files in os.walk('.'):
    if '.git' in root or '.venv' in root:
        continue
    for f in files:
        if f.endswith('.html'):
            html_files.append(os.path.join(root, f))

img_tag_pattern = re.compile(r'<img\s+[^>]*src=["\']([^"\']+)["\']', re.IGNORECASE)

for html_file in html_files:
    try:
        with open(html_file, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
        matches = img_tag_pattern.findall(content)
        for src in matches:
            # We want to find references that are just filenames, or not properly prefixed
            if not src.startswith('http') and not src.startswith('{{') and not src.startswith('/') and not src.startswith('data:'):
                print(f"File: {html_file} -> Found img src: '{src}'")
    except Exception as e:
        pass
