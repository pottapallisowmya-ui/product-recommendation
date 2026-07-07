import os
import glob

static_images_dir = 'static/images'
files_in_images = os.listdir(static_images_dir)

print(f"Files in static/images ({len(files_in_images)}):")
for f in files_in_images:
    print(f" - {f}")

print("\nSearching for references...")

# We will search in all files of these directories
search_dirs = ['frontend', 'backend', 'data', 'scripts', 'scratch']
found_references = {}

for root_dir in search_dirs:
    if not os.path.exists(root_dir):
        continue
    for root, dirs, files in os.walk(root_dir):
        # skip virtual envs or git if they are in these subdirs
        if '.git' in root or '.venv' in root or '__pycache__' in root:
            continue
        for file in files:
            file_path = os.path.join(root, file)
            # read file contents
            try:
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                
                # Check for each image filename
                for img in files_in_images:
                    # check both exact filename and name without extension
                    name_no_ext = os.path.splitext(img)[0]
                    if img in content:
                        found_references.setdefault(img, []).append((file_path, "exact"))
                    elif name_no_ext in content:
                        found_references.setdefault(img, []).append((file_path, "no_ext"))
            except Exception as e:
                # ignore unreadable files
                pass

print("\n--- Search Results ---")
if not found_references:
    print("No references found in codebase to any image in static/images!")
else:
    for img, refs in found_references.items():
        print(f"Image: {img}")
        for ref_path, ref_type in refs:
            print(f"  Referenced in: {ref_path} ({ref_type})")
