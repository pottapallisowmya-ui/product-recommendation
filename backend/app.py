from flask import Flask, render_template, request, redirect, url_for, session, jsonify
import urllib.parse
import os
import glob
import random
import time
import smtplib
from email.message import EmailMessage
from flask import make_response
from datetime import timedelta

base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
app = Flask(__name__, template_folder=os.path.join(base_dir, 'frontend', 'templates'), static_folder=os.path.join(base_dir, 'frontend', 'static'))
app.secret_key = 'smartshop_secret_key'
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=30)

@app.before_request
def make_session_permanent():
    session.permanent = True

import json
try:
    from chatbot import get_chatbot_response
except ImportError:
    from backend.chatbot import get_chatbot_response

def _pick_existing_static_image(pattern: str) -> str | None:
    matches = glob.glob(os.path.join(app.static_folder, pattern))
    if not matches:
        return None
    filename = os.path.basename(matches[0])
    return f"/static/{filename}"


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


def normalize_product_image(product):
    """Keep critical category images visible even when external hosts fail."""
    category = product.get("category", "")
    image = (product.get("image") or "").strip()
    product_id = product.get("id")

    # Ensure men fashion always has a local image fallback.
    if category == "Men Fashion":
        if image.startswith("/static/"):
            return
        local_men = _pick_existing_static_image(f"men_{product_id}_*.svg")
        product["image"] = local_men or "/static/placeholders/clothing.svg"
        return

    # Ensure toys always has a local image fallback.
    if category == "Toys":
        if image.startswith("/static/"):
            return
        local_toy = _pick_existing_static_image(f"toy_real_{product_id}.jpg")
        product["image"] = local_toy or "/static/placeholders/toys.svg"
        return

    # Ensure books always has a local image fallback.
    if category == "Books":
        # Convert OpenLibrary URL to Amazon Cover URL
        if "covers.openlibrary.org/b/isbn/" in image:
            isbn13 = image.split("isbn/")[1].split("-")[0]
            isbn10 = isbn13_to_isbn10(isbn13)
            if isbn10:
                image = f"https://images-na.ssl-images-amazon.com/images/P/{isbn10}.01.LZZZZZZZ.jpg"
                product["image"] = image
                if "images" in product:
                    product["images"] = [image]

        if image.startswith("/static/") or "images-na.ssl-images-amazon.com" in image or "images.amazon.com" in image:
            if "images" in product:
                product["images"] = [product["image"]]
            return
        name_lower = product.get("name", "").lower()
        if "alchemist" in name_lower:
            product["image"] = "/static/alchemist.jpg"
        elif any(kw in name_lower for kw in ["jobs", "diary", "freedom", "biography"]):
            product["image"] = "/static/book_biography.png"
        elif any(kw in name_lower for kw in ["rich dad", "zero to one", "lean startup", "good to great", "thinking, fast and slow", "business"]):
            product["image"] = "/static/book_business.png"
        elif any(kw in name_lower for kw in ["habits", "win friends", "habit", "grow rich", "sapiens", "self-help"]):
            product["image"] = "/static/book_selfhelp.png"
        elif any(kw in name_lower for kw in ["gatsby", "mockingbird", "1984", "prejudice", "catcher in the rye", "fiction", "novel"]):
            product["image"] = "/static/book_fiction.png"
        else:
            product["image"] = "/static/placeholders/books.svg"
        
        # Also clean up product["images"] to point to the new local image
        if "images" in product:
            product["images"] = [product["image"]]
        return


def normalize_products_images(products):
    for product in products:
        normalize_product_image(product)


# Load Mock Data
def load_catalog():
    try:
        try:
            from db import get_db_connection, setup_database, get_base_dir
        except ImportError:
            from backend.db import get_db_connection, setup_database, get_base_dir
        setup_database()
        conn = get_db_connection()
        products_db = conn.execute("SELECT * FROM products").fetchall()
        conn.close()
        
        products = [dict(p) for p in products_db]
        
        # Enrich with brand, color, size, and discount from catalog.json
        catalog_path = os.path.join(get_base_dir(), 'data', 'catalog.json')
        if os.path.exists(catalog_path):
            with open(catalog_path, 'r', encoding='utf-8') as f:
                catalog = json.load(f)
            catalog_map = {p['id']: p for p in catalog if 'id' in p}
            for p in products:
                cat_item = catalog_map.get(p['id'])
                if cat_item:
                    for k, v in cat_item.items():
                        if k not in p:
                            p[k] = v
        for p in products:
            normalize_product_image(p)
        return products
    except Exception as e:
        print("Failed to load catalog.json:", e)
        return []

mock_products = load_catalog()
# Import the ML model

# Import the ML model
try:
    from model import get_user_recommendations
except ImportError:
    from backend.model import get_user_recommendations

def extract_user_history_ids():
    ids = set()
    user = session.get('user')
    if user:
        try:
            from db import get_db_connection
        except ImportError:
            from backend.db import get_db_connection
        conn = get_db_connection()
        rows = conn.execute("SELECT product_id FROM carts WHERE email = ?", (user,)).fetchall()
        for r in rows: ids.add(r['product_id'])
        rows = conn.execute("SELECT product_id FROM saved_items WHERE email = ?", (user,)).fetchall()
        for r in rows: ids.add(r['product_id'])
        rows = conn.execute("SELECT items_json FROM orders WHERE email = ?", (user,)).fetchall()
        for r in rows:
            items = json.loads(r['items_json'])
            for it in items: ids.add(it.get('id', 0))
        conn.close()
    else:
        cart_items = session.get('cart') if session.get('cart') is not None else mock_cart_items
        for item in cart_items:
            match = next((p for p in mock_products if p.get('name') == item.get('name')), None)
            if match:
                ids.add(match.get('id'))
    return list(ids)

mock_cart_items = [
    {
        "name": "Sony WH-1000XM4", 
        "price": 24999, 
        "quantity": 2,
        "image": "https://images.unsplash.com/photo-1505740420928-5e560c06d30e?q=80&w=1000&auto=format&fit=crop"
    }
]

def get_filtered_products(args):
    # reload catalog each request so updates to catalog.json are picked up without restarting
    display_products = load_catalog()
    
    # Extract query params supporting both legacy '?filter=X&val=Y' and new multi-params '?category=X&brand=Y'
    filter_type = args.get('filter')
    val = args.get('val')
    range_val = args.get('range')
    
    category = args.get('category') or (val if filter_type == 'category' else None)
    search = args.get('search') or (val if filter_type == 'search' else None)
    brand = args.get('brand') or (val if filter_type == 'brand' else None)
    discount = args.get('discount') or (val if filter_type == 'discount' else None)
    price = args.get('price') or (range_val if filter_type == 'price' else None)
    max_price = args.get('max_price')
    rating = args.get('rating') or (val if filter_type == 'rating' else None)
    popularity = args.get('popularity') or (val if filter_type == 'popularity' else None)
    sort = args.get('sort')
    
    if category:
        display_products = [p for p in display_products if p.get('category', '').lower() == category.lower()]
        
    cat_min = 0
    cat_max = 200000
    if display_products:
        cat_min = min(p.get('price', 0) for p in display_products)
        cat_max = max(p.get('price', 0) for p in display_products)
        
    if search:
        q = search.lower()
        
        # Smart synonym mapping for better semantic search matches
        synonyms = {
            "phone": ["iphone", "smartphone", "mobile", "galaxy", "cellphone"],
            "shoes": ["sneakers", "footwear", "running", "air max"],
            "tv": ["television", "smart tv", "screen", "display"],
            "clothes": ["fashion", "shirt", "jeans", "t-shirt", "jacket", "activewear"],
            "laptop": ["computer", "notebook", "inspiron", "macbook", "pc"],
            "watch": ["smartwatch", "wearable", "timepiece"],
            "earphones": ["headphones", "airpods", "buds", "headset"],
            "audio": ["headphones", "airpods", "buds", "headset", "speaker"]
        }
        
        search_terms = [q]
        for key, related in synonyms.items():
            if key in q or q in key:
                search_terms.extend(related)
                
        def product_matches_search(p):
            p_text = (p.get('name', '') + ' ' + p.get('description', '') + ' ' + p.get('category', '')).lower()
            return any(term in p_text for term in search_terms)
            
        display_products = [p for p in display_products if product_matches_search(p)]
        
    if brand:
        display_products = [p for p in display_products if brand.lower() in p.get('name', '').lower() or brand.lower() in p.get('description', '').lower()]
        
    if discount:
        try:
            d = int(discount)
            display_products = [p for p in display_products if p.get('discount', 0) >= d]
        except ValueError: pass
        
    if price:
        if price == 'under_1000':
            display_products = [p for p in display_products if p.get('price', 0) < 1000]
        elif price == '1000_5000':
            display_products = [p for p in display_products if 1000 <= p.get('price', 0) <= 5000]
        elif price == '5000_20000':
            display_products = [p for p in display_products if 5000 < p.get('price', 0) <= 20000]
        elif price == 'over_20000':
            display_products = [p for p in display_products if p.get('price', 0) > 20000]
        elif price == 'over_5000':
            display_products = [p for p in display_products if p.get('price', 0) > 5000]
            
    if max_price:
        try:
            m = int(max_price)
            display_products = [p for p in display_products if p.get('price', 0) <= m]
        except ValueError: pass
            
    if rating:
        try:
            r = float(rating)
            display_products = [p for p in display_products if p.get('rating', 0) >= r]
        except ValueError: pass
        
    if popularity:
        if popularity == 'bestsellers':
            display_products = [p for p in display_products if p.get('popularity') or p.get('price', 0) > 20000]
        elif popularity == 'trending':
            history_ids = extract_user_history_ids()
            recs = get_user_recommendations(history_ids, mock_products, num_recommendations=20)
            rec_ids = {p['id'] for p in recs}
            display_products = [p for p in display_products if p.get('id') in rec_ids]

    if sort:
        if sort == 'low_to_high':
            display_products.sort(key=lambda x: x.get('price', 0))
        elif sort == 'high_to_low':
            display_products.sort(key=lambda x: x.get('price', 0), reverse=True)

    import random
    for p in display_products:
        normalize_product_image(p)
        base_price = p.get('price', 0)
        p['competitor_prices'] = {
            'SmartShop': base_price,
            'Amazon': int(base_price * random.uniform(0.85, 1.15)),
            'Flipkart': int(base_price * random.uniform(0.85, 1.15)),
            'Myntra': int(base_price * random.uniform(0.85, 1.15))
        }
        p['cheapest_platform'] = min(p['competitor_prices'], key=p['competitor_prices'].get)

    return display_products, category, cat_min, cat_max

@app.route('/api/chat', methods=['POST'])
def api_chat():
    data = request.get_json() or {}
    msg = data.get('message', '')
    try:
        response = get_chatbot_response(msg)
    except Exception as e:
        app.logger.error(f'Chatbot error: {e}')
        response = {'reply': "Sorry, I'm having trouble connecting right now.", 'recommendations': []}
    return jsonify(response)

@app.route("/")
def index():
    # Allow anonymous users to view the storefront on the root route.
    # Previously this redirected to login which hid products for unauthenticated visitors.
    products, active_category, cat_min, cat_max = get_filtered_products(request.args)
    show_modal = False
    if session.get('show_new_user_quiz'):
        show_modal = True
        session.pop('show_new_user_quiz', None)
    return render_template("index.html", products=products, active_category=active_category, cat_min=cat_min, cat_max=cat_max, show_new_user_modal=show_modal)

@app.route("/dashboard")
def dashboard():
    history_ids = extract_user_history_ids()
    recommended_products = get_user_recommendations(history_ids, mock_products, num_recommendations=6)
    return render_template("dashboard.html", recommendations=recommended_products)

@app.route('/quiz', methods=['GET'])
def quiz():
    return render_template('quiz.html', active_category=None)

def get_styled_outfits(products, vibe=None):
    """Returns dynamic outfit arrays by extracting items from the database based on vibe."""
    try:
        from db import get_db_connection
    except ImportError:
        from backend.db import get_db_connection
        
    conn = get_db_connection()
    c = conn.cursor()
    
    women_outfit = []
    men_outfit = []
    
    if vibe:
        # Perfect outfit curation based on vibe
        if vibe == 'cool':
            w_items = c.execute("SELECT * FROM products WHERE category='Women Fashion' AND (name LIKE '%Crop%' OR name LIKE '%Jacket%' OR name LIKE '%Hoodie%' OR name LIKE '%Streetwear%') ORDER BY RANDOM() LIMIT 1").fetchall()
            if not w_items: w_items = c.execute("SELECT * FROM products WHERE category='Women Fashion' ORDER BY RANDOM() LIMIT 1").fetchall()
            w_shoes = c.execute("SELECT * FROM products WHERE category='Shoes' AND (name LIKE '%Sneaker%' OR name LIKE '%Nike%' OR name LIKE '%Adidas%' OR name LIKE '%Puma%') ORDER BY RANDOM() LIMIT 1").fetchall()
            if not w_shoes: w_shoes = c.execute("SELECT * FROM products WHERE category='Shoes' ORDER BY RANDOM() LIMIT 1").fetchall()
            w_acc = c.execute("SELECT * FROM products WHERE (category='Electronics' AND (name LIKE '%Headphones%' OR name LIKE '%Earbuds%' OR name LIKE '%AirPods%' OR name LIKE '%Watch%')) OR (category='Beauty' AND name LIKE '%Perfume%') ORDER BY RANDOM() LIMIT 1").fetchall()
            if not w_acc: w_acc = c.execute("SELECT * FROM products WHERE category='Beauty' OR category='Electronics' ORDER BY RANDOM() LIMIT 1").fetchall()
            
            m_items = c.execute("SELECT * FROM products WHERE category='Men Fashion' AND (name LIKE '%Denim%' OR name LIKE '%Hoodie%' OR name LIKE '%Jacket%') ORDER BY RANDOM() LIMIT 1").fetchall()
            if not m_items: m_items = c.execute("SELECT * FROM products WHERE category='Men Fashion' ORDER BY RANDOM() LIMIT 1").fetchall()
            m_shoes = c.execute("SELECT * FROM products WHERE category='Shoes' AND (name LIKE '%Sneaker%' OR name LIKE '%Nike%' OR name LIKE '%Adidas%' OR name LIKE '%Puma%') ORDER BY RANDOM() LIMIT 1").fetchall()
            if not m_shoes: m_shoes = c.execute("SELECT * FROM products WHERE category='Shoes' ORDER BY RANDOM() LIMIT 1").fetchall()
            m_acc = c.execute("SELECT * FROM products WHERE category='Electronics' AND (name LIKE '%Headphones%' OR name LIKE '%Earbuds%' OR name LIKE '%AirPods%' OR name LIKE '%Watch%' OR name LIKE '%Speaker%') ORDER BY RANDOM() LIMIT 1").fetchall()
            if not m_acc: m_acc = c.execute("SELECT * FROM products WHERE category='Electronics' ORDER BY RANDOM() LIMIT 1").fetchall()
            
        elif vibe == 'professional':
            w_items = c.execute("SELECT * FROM products WHERE category='Women Fashion' AND (name LIKE '%Blazer%' OR name LIKE '%Shirt%' OR name LIKE '%Dress%' OR name LIKE '%Formal%') ORDER BY RANDOM() LIMIT 1").fetchall()
            if not w_items: w_items = c.execute("SELECT * FROM products WHERE category='Women Fashion' ORDER BY RANDOM() LIMIT 1").fetchall()
            w_shoes = c.execute("SELECT * FROM products WHERE category='Shoes' AND (name LIKE '%Oxford%' OR name LIKE '%Classic%' OR name LIKE '%Walk%') ORDER BY RANDOM() LIMIT 1").fetchall()
            if not w_shoes: w_shoes = c.execute("SELECT * FROM products WHERE category='Shoes' ORDER BY RANDOM() LIMIT 1").fetchall()
            w_acc = c.execute("SELECT * FROM products WHERE (category='Books' AND (name LIKE '%Steve Jobs%' OR name LIKE '%Win Friends%' OR name LIKE '%Habit%' OR name LIKE '%Great%' OR name LIKE '%Zero to One%')) OR (category='Electronics' AND (name LIKE '%Laptop%' OR name LIKE '%Notebook%' OR name LIKE '%Tablet%' OR name LIKE '%iPad%')) ORDER BY RANDOM() LIMIT 1").fetchall()
            if not w_acc: w_acc = c.execute("SELECT * FROM products WHERE category='Books' OR category='Electronics' ORDER BY RANDOM() LIMIT 1").fetchall()
            
            # Men's pro look is hardcoded to the injected lookbook
            m_items = c.execute("SELECT * FROM products WHERE id IN (9004)").fetchall()
            m_acc = c.execute("SELECT * FROM products WHERE id IN (9005)").fetchall()
            m_shoes = c.execute("SELECT * FROM products WHERE id IN (9006)").fetchall()
            
        elif vibe == 'party':
            # Women's party look is hardcoded
            w_items = c.execute("SELECT * FROM products WHERE id IN (9001)").fetchall()
            w_acc = c.execute("SELECT * FROM products WHERE id IN (9002)").fetchall()
            w_shoes = c.execute("SELECT * FROM products WHERE id IN (9003)").fetchall()
            
            m_items = c.execute("SELECT * FROM products WHERE category='Men Fashion' AND (name LIKE '%Shirt%' OR name LIKE '%Jacket%' OR name LIKE '%Polo%') ORDER BY RANDOM() LIMIT 1").fetchall()
            if not m_items: m_items = c.execute("SELECT * FROM products WHERE category='Men Fashion' ORDER BY RANDOM() LIMIT 1").fetchall()
            m_shoes = c.execute("SELECT * FROM products WHERE category='Shoes' AND (name LIKE '%Sneaker%' OR name LIKE '%Adidas%' OR name LIKE '%Nike%' OR name LIKE '%Puma%') ORDER BY RANDOM() LIMIT 1").fetchall()
            if not m_shoes: m_shoes = c.execute("SELECT * FROM products WHERE category='Shoes' ORDER BY RANDOM() LIMIT 1").fetchall()
            m_acc = c.execute("SELECT * FROM products WHERE (category='Electronics' AND (name LIKE '%Watch%' OR name LIKE '%Speaker%')) OR (category='Beauty' AND name LIKE '%Perfume%') ORDER BY RANDOM() LIMIT 1").fetchall()
            if not m_acc: m_acc = c.execute("SELECT * FROM products WHERE name LIKE '%Watch%' ORDER BY RANDOM() LIMIT 1").fetchall()
            
        elif vibe == 'comfort':
            # Women's comfort look is hardcoded
            w_items = c.execute("SELECT * FROM products WHERE id IN (9007)").fetchall()
            w_acc = c.execute("SELECT * FROM products WHERE category='Beauty' AND (name LIKE '%Moisture%' OR name LIKE '%Serum%' OR name LIKE '%Perfume%') ORDER BY RANDOM() LIMIT 1").fetchall()
            w_shoes = c.execute("SELECT * FROM products WHERE category='Shoes' AND (name LIKE '%Sneaker%' OR name LIKE '%Running%' OR name LIKE '%Walk%') ORDER BY RANDOM() LIMIT 1").fetchall()
            if not w_shoes: w_shoes = c.execute("SELECT * FROM products WHERE category='Shoes' ORDER BY RANDOM() LIMIT 1").fetchall()
            
            m_items = c.execute("SELECT * FROM products WHERE category='Men Fashion' AND (name LIKE '%T-Shirt%' OR name LIKE '%Sweat%' OR name LIKE '%Hoodie%' OR name LIKE '%Jogger%') ORDER BY RANDOM() LIMIT 1").fetchall()
            if not m_items: m_items = c.execute("SELECT * FROM products WHERE category='Men Fashion' ORDER BY RANDOM() LIMIT 1").fetchall()
            m_shoes = c.execute("SELECT * FROM products WHERE category='Shoes' AND (name LIKE '%Sneaker%' OR name LIKE '%Running%' OR name LIKE '%Walk%') ORDER BY RANDOM() LIMIT 1").fetchall()
            if not m_shoes: m_shoes = c.execute("SELECT * FROM products WHERE category='Shoes' ORDER BY RANDOM() LIMIT 1").fetchall()
            m_acc = []
            
        else:
            w_items = c.execute("SELECT * FROM products WHERE category='Women Fashion' ORDER BY RANDOM() LIMIT 1").fetchall()
            w_acc = c.execute("SELECT * FROM products WHERE category='Beauty' ORDER BY RANDOM() LIMIT 1").fetchall()
            w_shoes = c.execute("SELECT * FROM products WHERE category='Shoes' ORDER BY RANDOM() LIMIT 1").fetchall()
            m_items = c.execute("SELECT * FROM products WHERE category='Men Fashion' ORDER BY RANDOM() LIMIT 1").fetchall()
            m_acc = c.execute("SELECT * FROM products WHERE category='Electronics' ORDER BY RANDOM() LIMIT 1").fetchall()
            m_shoes = c.execute("SELECT * FROM products WHERE category='Shoes' ORDER BY RANDOM() LIMIT 1").fetchall()

        if w_items and w_shoes: 
            women_outfit = [dict(w_items[0]), dict(w_shoes[0])]
            if w_acc: women_outfit.insert(1, dict(w_acc[0]))
        
        if m_items and m_shoes: 
            men_outfit = [dict(m_items[0]), dict(m_shoes[0])]
            if m_acc: men_outfit.insert(1, dict(m_acc[0]))

    else:
        # Fallback to the original logic for quiz_results where vibe is None
        w_f = next((p for p in products if p.get('category') == 'Women Fashion'), None)
        w_b = next((p for p in products if p.get('category') == 'Beauty'), None)
        w_s = next((p for p in products if p.get('category') == 'Shoes'), None)
        if w_f and w_s:
            women_outfit = [w_f, w_b, w_s] if w_b else [w_f, w_s]
            
        m_f = next((p for p in products if p.get('category') == 'Men Fashion'), None)
        m_s = next((p for p in products if p.get('category') == 'Shoes' and p != w_s), None)
        if not m_s:
            m_s = next((p for p in products if p.get('category') == 'Shoes'), None)
            
        if m_f and m_s:
            men_outfit = [m_f, m_s]
            
    for p in women_outfit:
        normalize_product_image(p)
    for p in men_outfit:
        normalize_product_image(p)
    conn.close()
    return women_outfit, men_outfit

@app.route('/quiz/results', methods=['POST', 'GET'])
def quiz_results():
    if request.method == 'POST':
        category = request.form.get('category')
        budget = request.form.get('budget')
        purpose = request.form.get('purpose')
        experience = request.form.get('experience')
        priority = request.form.get('priority')
    else:
        return redirect(url_for('quiz'))
        
    try:
        from db import get_db_connection
    except ImportError:
        from backend.db import get_db_connection
        
    conn = get_db_connection()
    c = conn.cursor()
    
    # Base query for category and budget
    query = "SELECT * FROM products WHERE 1=1"
    params = []
    
    # 1. Category logic
    if category == 'Fashion':
        query += " AND category IN ('Men Fashion', 'Women Fashion', 'Kidsware', 'Shoes')"
    elif category == 'Other':
        query += " AND category IN ('Toys', 'Home Appliances')"
    elif category:
        query += " AND category = ?"
        params.append(category)
        
    # 2. Budget logic
    if budget == 'under_500':
        query += " AND price < 500"
    elif budget == '500_2000':
        query += " AND price >= 500 AND price <= 2000"
    elif budget == '2000_10000':
        query += " AND price > 2000 AND price <= 10000"
    elif budget == 'above_10000':
        query += " AND price > 10000"
        
    # 3. Priority / Sorting logic
    order_part = ""
    if priority == 'Price':
        order_part = " ORDER BY price ASC"
    elif priority == 'Quality':
        order_part = " ORDER BY rating DESC"
    elif priority == 'Brand':
        order_part = " ORDER BY popularity DESC, rating DESC"
    elif priority == 'Trends':
        order_part = " ORDER BY popularity DESC"
    else:
        order_part = " ORDER BY rating DESC"

    # Strict query with all filters
    strict_query = query
    if purpose == 'Daily':
        strict_query += " AND (rating >= 3.5 OR popularity = 1)"
    elif purpose == 'Gift':
        strict_query += " AND rating >= 4.0"
        
    if experience == 'Expert':
        strict_query += " AND rating >= 4.5"
    elif experience == 'Beginner':
        strict_query += " AND popularity = 1"

    products_raw = c.execute(strict_query + order_part + " LIMIT 20", params).fetchall()
    msg = "Here are your perfect matches!"
    
    if len(products_raw) == 0:
        # Fallback 1: Drop purpose and experience
        products_raw = c.execute(query + order_part + " LIMIT 20", params).fetchall()
        msg = "We couldn't perfectly match your purpose, but here are some options in your budget!"
        
    if len(products_raw) == 0:
        # Fallback 2: Drop budget
        base_cat_query = "SELECT * FROM products WHERE 1=1"
        base_params = []
        if category == 'Fashion':
            base_cat_query += " AND category IN ('Men Fashion', 'Women Fashion', 'Kidsware', 'Shoes')"
        elif category == 'Other':
            base_cat_query += " AND category IN ('Toys', 'Home Appliances')"
        elif category:
            base_cat_query += " AND category = ?"
            base_params.append(category)
        
        products_raw = c.execute(base_cat_query + order_part + " LIMIT 20", base_params).fetchall()
        msg = "We couldn't find items in that budget, but here are related top items!"
        
    if len(products_raw) == 0:
        # Fallback 3: Drop everything
        products_raw = c.execute("SELECT * FROM products" + order_part + " LIMIT 20").fetchall()
        msg = "Here are some top items across the store!"
        
    conn.close()
    
    products = [dict(p) for p in products_raw]
    for p in products:
        normalize_product_image(p)
    
    women_outfit, men_outfit = get_styled_outfits(products, None)            
    return render_template('quiz_results.html', products=products, message=msg, active_category=category, women_outfit=women_outfit, men_outfit=men_outfit)

@app.route('/mood')
def mood_selector():
    return render_template('mood.html')

@app.route('/mood/<vibe>')
def mood_results(vibe):
    try:
        from db import get_db_connection
    except ImportError:
        from backend.db import get_db_connection
        
    conn = get_db_connection()
    c = conn.cursor()
    query = "SELECT * FROM products WHERE category NOT IN ('Kidsware', 'Toys')"
    
    if vibe == 'cool':
        # Cool vibe: Tech-savvy, trendy, Gen-Z feel
        query += """ AND (
            (category = 'Electronics' AND (name LIKE '%Headphones%' OR name LIKE '%Earbuds%' OR name LIKE '%AirPods%' OR name LIKE '%Watch%' OR name LIKE '%LED%' OR name LIKE '%Speaker%')) OR
            (category = 'Books' AND (name LIKE '%Atomic Habits%' OR name LIKE '%Habit%' OR name LIKE '%Rich Dad%' OR name LIKE '%Win Friends%' OR name LIKE '%Steve Jobs%' OR name LIKE '%Zero to One%' OR name LIKE '%Lean Startup%')) OR
            (category = 'Home Appliances' AND (name LIKE '%Fridge%' OR name LIKE '%Refrigerator%' OR name LIKE '%Coffee%')) OR
            (category = 'Beauty' AND (name LIKE '%Serum%' OR name LIKE '%Moisture%' OR name LIKE '%Perfume%')) OR
            (category = 'Women Fashion' AND (name LIKE '%Crop%' OR name LIKE '%Hoodie%' OR name LIKE '%Streetwear%')) OR
            (category = 'Men Fashion' AND (name LIKE '%T-Shirt%' OR name LIKE '%Denim%' OR name LIKE '%Jacket%')) OR
            (category = 'Shoes' AND (name LIKE '%Sneaker%' OR name LIKE '%Nike%' OR name LIKE '%Adidas%' OR name LIKE '%Puma%'))
        ) ORDER BY RANDOM() LIMIT 15"""
        msg = "😎 Cool Vibe Activated. Check out these fresh styles!"
    elif vibe == 'professional':
        # Always fetch core professional items first (suit, briefcase, shoes, formal shirt, trousers, blazer)
        core_raw = c.execute("SELECT * FROM products WHERE id IN (9004, 9005, 9006, 145, 63, 9015)").fetchall()
        core_ids = [p['id'] for p in core_raw]
        
        # Fetch other professional items randomly
        other_raw = c.execute(f"""SELECT * FROM products WHERE id NOT IN ({','.join(map(str, core_ids))}) AND (
            (category = 'Electronics' AND (name LIKE '%Laptop%' OR name LIKE '%Notebook%' OR name LIKE '%Tablet%' OR name LIKE '%iPad%' OR name LIKE '%MacBook%' OR name LIKE '%Monitor%' OR name LIKE '%Mouse%' OR name LIKE '%Keyboard%')) OR
            (category = 'Books' AND (name LIKE '%Steve Jobs%' OR name LIKE '%Thinking, Fast and Slow%' OR name LIKE '%Win Friends%' OR name LIKE '%Habit%' OR name LIKE '%Great%' OR name LIKE '%Zero to One%' OR name LIKE '%Lean Startup%' OR name LIKE '%Think and Grow Rich%')) OR
            (category = 'Men Fashion' AND (name LIKE '%Formal%' OR name LIKE '%Shirt%' OR name LIKE '%Trouser%' OR name LIKE '%Blazer%' OR name LIKE '%Suit%' OR name LIKE '%Briefcase%' OR name LIKE '%Chino%')) OR
            (category = 'Women Fashion' AND (name LIKE '%Blazer%' OR name LIKE '%Shirt%' OR name LIKE '%Formal%' OR name LIKE '%Suit%')) OR
            (category = 'Shoes' AND (name LIKE '%Oxford%' OR name LIKE '%Classic%' OR name LIKE '%Formal%' OR name LIKE '%Leather%'))
        ) ORDER BY RANDOM() LIMIT 9""").fetchall()
        
        products_raw = core_raw + other_raw
        msg = "💼 Professional Edge"
    elif vibe == 'party':
        query += """ AND (
            (category = 'Beauty' AND (name LIKE '%Lipstick%' OR name LIKE '%Palette%' OR name LIKE '%Gloss%' OR name LIKE '%Mascara%' OR name LIKE '%Kajal%' OR name LIKE '%Perfume%')) OR
            (category = 'Women Fashion' AND (name LIKE '%Dress%' OR name LIKE '%Gown%' OR name LIKE '%Crop%')) OR
            (category = 'Men Fashion' AND (name LIKE '%Shirt%' OR name LIKE '%Polo%' OR name LIKE '%Jeans%' OR name LIKE '%Jacket%')) OR
            (category = 'Shoes' AND (name LIKE '%Heels%' OR name LIKE '%Party%' OR name LIKE '%Sneaker%')) OR
            (category = 'Electronics' AND (name LIKE '%Speaker%' OR name LIKE '%TV%' OR name LIKE '%AirPods%')) OR
            (id IN (9001, 9002, 9003))
        ) ORDER BY RANDOM() LIMIT 15"""
        msg = "🎉 Party Glam"
    elif vibe == 'comfort':
        query += " AND ((category IN ('Women Fashion', 'Men Fashion') AND (name LIKE '%Sweat%' OR name LIKE '%Cozy%' OR name LIKE '%Hoodie%' OR name LIKE '%T-Shirt%' OR name LIKE '%Jogger%')) OR (category = 'Shoes' AND (name LIKE '%Sneaker%' OR name LIKE '%Running%' OR name LIKE '%Walk%')) OR id IN (9007, 9010, 9011, 9012, 9013, 9014, 9017)) ORDER BY RANDOM() LIMIT 15"
        msg = "🧘 Cozy Comfort"
    else:
        query += " LIMIT 15"
        msg = "Here are your products!"
        
    # Execute query only if products_raw hasn't been set by professional logic
    if vibe != 'professional':
        products_raw = c.execute(query).fetchall()
        
    conn.close()
    
    products = [dict(p) for p in products_raw]
    for p in products:
        normalize_product_image(p)
    women_outfit, men_outfit = get_styled_outfits(products, vibe)
    
    # ensure lookbooks are removed from standard grid so they don't duplicate (except for professional vibe core items)
    if women_outfit:
        for item in women_outfit:
            if vibe == 'professional' and item['id'] in (9004, 9005, 9006, 9015):
                continue
            products = [p for p in products if p['id'] != item['id']]
    if men_outfit:
        for item in men_outfit:
            if vibe == 'professional' and item['id'] in (9004, 9005, 9006, 9015):
                continue
            products = [p for p in products if p['id'] != item['id']]
            
    return render_template('quiz_results.html', products=products, message=msg, women_outfit=women_outfit, men_outfit=men_outfit)


@app.route("/home")
def home():
    products, active_category, cat_min, cat_max = get_filtered_products(request.args)
    show_modal = False
    if session.get('show_new_user_quiz'):
        show_modal = True
        session.pop('show_new_user_quiz', None)
    return render_template("index.html", products=products, active_category=active_category, cat_min=cat_min, cat_max=cat_max, show_new_user_modal=show_modal)

@app.route("/products")
def products():
    products, active_category, cat_min, cat_max = get_filtered_products(request.args)
    return render_template("products.html", products=products, active_category=active_category, cat_min=cat_min, cat_max=cat_max)

@app.route("/product/<int:product_id>")
def product_detail(product_id):
    if 'user' not in session:
        return redirect(url_for('login'))
        
    product = next((p for p in mock_products if p.get('id') == product_id), None)
    if not product:
        return "Product not found", 404
        
    # Generate some mock reviews based on the product
    reviews = [
        {"user": "Alex", "rating": 5, "comment": "Absolutely love this! The quality is amazing.", "date": "10 Oct 2023"},
        {"user": "Priya", "rating": 4, "comment": "Very good, but shipping took a bit long.", "date": "15 Sep 2023"},
        {"user": "John", "rating": 5, "comment": "Exceeded my expectations. Great value for the price.", "date": "22 Aug 2023"}
    ]
    
    # Try to extract a brand name from the product name
    brand_name = "Premium Brand"
    words = product.get('name', '').split()
    if words:
        brand_name = words[0] # Usually the first word is the brand (e.g. "Apple MacBook", "Nike Air")
        
    active_category = product.get('category')
    
    # Generate Smart Price Comparison Logic (Aggregator Model)
    import random
    base_price = product.get('price', 0)
    
    # Randomly fluctuate competitor prices between -15% and +15%
    competitor_prices = {
        'SmartShop': base_price,
        'Amazon': int(base_price * random.uniform(0.85, 1.15)),
        'Flipkart': int(base_price * random.uniform(0.85, 1.15)),
        'Myntra': int(base_price * random.uniform(0.85, 1.15))
    }
    
    # Determine the cheapest platform
    cheapest_platform = min(competitor_prices, key=competitor_prices.get)
    
    return render_template('product_detail.html', product=product, reviews=reviews, brand_name=brand_name, active_category=active_category, competitor_prices=competitor_prices, cheapest_platform=cheapest_platform)



@app.route("/cart")
def cart():
    user = session.get('user')
    items = []
    if user:
        try: from db import get_db_connection
        except ImportError: from backend.db import get_db_connection
        conn = get_db_connection()
        rows = conn.execute("SELECT * FROM carts WHERE email = ?", (user,)).fetchall()
        for r in rows:
            product = next((p for p in mock_products if p.get('id') == r['product_id']), None)
            if product:
                item = dict(product)
                item['quantity'] = r['quantity']
                items.append(item)
        conn.close()

    subtotal = sum(item.get('price', 0) * item.get('quantity', 0) for item in items)
    total_items = sum(item.get('quantity', 0) for item in items)
    return render_template("cart.html", items=items, subtotal=subtotal, total_items=total_items, products=mock_products)


@app.route('/api/cart/delete', methods=['POST'])
def api_cart_delete():
    data = request.get_json() or {}
    try: product_id = int(data.get('product_id'))
    except Exception: return jsonify({'error': 'invalid product id'}), 400

    user = session.get('user')
    if not user: return jsonify({'error': 'login_required'}), 401

    try: from db import get_db_connection
    except ImportError: from backend.db import get_db_connection
    conn = get_db_connection()
    conn.execute("DELETE FROM carts WHERE email = ? AND product_id = ?", (user, product_id))
    conn.commit()
    r = conn.execute("SELECT SUM(quantity) FROM carts WHERE email = ?", (user,)).fetchone()[0]
    conn.close()
    return jsonify({'success': True, 'total_items': r or 0})


@app.route('/api/cart/save', methods=['POST'])
def api_cart_save():
    data = request.get_json() or {}
    try: product_id = int(data.get('product_id'))
    except Exception: return jsonify({'error': 'invalid product id'}), 400

    user = session.get('user')
    if not user: return jsonify({'error': 'login_required'}), 401
    
    try: from db import get_db_connection
    except ImportError: from backend.db import get_db_connection
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("DELETE FROM carts WHERE email = ? AND product_id = ?", (user, product_id))
    c.execute("INSERT OR IGNORE INTO saved_items (email, product_id) VALUES (?, ?)", (user, product_id))
    conn.commit()
    r = conn.execute("SELECT SUM(quantity) FROM carts WHERE email = ?", (user,)).fetchone()[0] or 0
    s = conn.execute("SELECT COUNT(*) FROM saved_items WHERE email = ?", (user,)).fetchone()[0] or 0
    conn.close()

    return jsonify({'success': True, 'total_items': r, 'saved_count': s})


@app.route('/api/saved/add', methods=['POST'])
def api_saved_add():
    data = request.get_json() or {}
    try: product_id = int(data.get('product_id'))
    except Exception: return jsonify({'error': 'invalid product id'}), 400

    user = session.get('user')
    if not user: return jsonify({'error': 'login_required'}), 401

    try: from db import get_db_connection
    except ImportError: from backend.db import get_db_connection
    conn = get_db_connection()
    conn.execute("INSERT OR IGNORE INTO saved_items (email, product_id) VALUES (?, ?)", (user, product_id))
    conn.commit()
    s = conn.execute("SELECT COUNT(*) FROM saved_items WHERE email = ?", (user,)).fetchone()[0] or 0
    conn.close()

    return jsonify({'success': True, 'saved_count': s})


@app.route('/saved')
def saved():
    user = session.get('user')
    if not user: return redirect(url_for('login'))
    
    try: from db import get_db_connection
    except ImportError: from backend.db import get_db_connection
    conn = get_db_connection()
    rows = conn.execute("SELECT product_id FROM saved_items WHERE email = ?", (user,)).fetchall()
    
    saved_items = []
    for r in rows:
        product = next((p for p in mock_products if p.get('id') == r['product_id']), None)
        if product: saved_items.append(product)
    conn.close()
    return render_template('saved.html', items=saved_items)


@app.route('/api/saved/move', methods=['POST'])
def api_saved_move():
    data = request.get_json() or {}
    try: product_id = int(data.get('product_id'))
    except Exception: return jsonify({'error': 'invalid product id'}), 400

    user = session.get('user')
    if not user: return jsonify({'error': 'login_required'}), 401

    try: from db import get_db_connection
    except ImportError: from backend.db import get_db_connection
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("DELETE FROM saved_items WHERE email = ? AND product_id = ?", (user, product_id))
    if c.rowcount > 0:
        # It was actually in saved_items, move back to cart
        c.execute("SELECT quantity FROM carts WHERE email = ? AND product_id = ?", (user, product_id))
        row = c.fetchone()
        if row: c.execute("UPDATE carts SET quantity = quantity + 1 WHERE email = ? AND product_id = ?", (user, product_id))
        else: c.execute("INSERT INTO carts (email, product_id, quantity) VALUES (?, ?, 1)", (user, product_id))
    conn.commit()
    r = conn.execute("SELECT SUM(quantity) FROM carts WHERE email = ?", (user,)).fetchone()[0] or 0
    s = conn.execute("SELECT COUNT(*) FROM saved_items WHERE email = ?", (user,)).fetchone()[0] or 0
    conn.close()

    return jsonify({'success': True, 'total_items': r, 'saved_count': s})


@app.route('/checkout', methods=['GET', 'POST'])
def checkout():
    user = session.get('user')
    if not user: return redirect(url_for('login'))
    
    try: from db import get_db_connection
    except ImportError: from backend.db import get_db_connection
    conn = get_db_connection()
    c = conn.cursor()
    rows = c.execute("SELECT * FROM carts WHERE email = ?", (user,)).fetchall()
    items = []
    for r in rows:
        p = next((x for x in mock_products if x.get('id') == r['product_id']), None)
        if p:
            it = dict(p)
            it['quantity'] = r['quantity']
            items.append(it)
    subtotal = sum(it.get('price', 0) * it.get('quantity', 0) for it in items)
    
    if request.method == 'GET':
        conn.close()
        return render_template('checkout.html', products=mock_products, subtotal=subtotal)

    payment_method = request.form.get('payment_method')
    use_emi = request.form.get('use_emi') is not None or request.form.get('emi')
    upi_id = request.form.get('upi_id')

    order = {
        'id': session.get('order_counter', 1000) + 1,
        'items': items,
        'total': subtotal,
        'payment_method': str(payment_method) + (" (EMI)" if use_emi else (" - UPI:"+upi_id if upi_id else ""))
    }

    if payment_method == 'upi':
        if not upi_id or '@' not in upi_id:
            session['last_order'] = order
            conn.close()
            return render_template('upi_payment.html', upi_uri=None, qr=None, order=order, error='Please enter a valid UPI ID (for example: alice@bank or alice@upi). If you only entered a phone number, open your UPI app and add a VPA, then try again.')
        upi_uri = f"upi://pay?pa={urllib.parse.quote(upi_id)}&pn={urllib.parse.quote('SmartShop')}&am={urllib.parse.quote(str(subtotal))}&cu=INR"
        qr = f"https://api.qrserver.com/v1/create-qr-code/?size=300x300&data={urllib.parse.quote(upi_uri)}"
        session['last_order'] = order
        conn.close()
        return render_template('upi_payment.html', upi_uri=upi_uri, qr=qr, order=order, error=None)

    c.execute("INSERT INTO orders (email, total, payment_method, items_json) VALUES (?, ?, ?, ?)",
              (user, subtotal, order['payment_method'], json.dumps(items)))
    order['id'] = c.lastrowid
    session['last_order'] = order
    c.execute("DELETE FROM carts WHERE email = ?", (user,))
    conn.commit()
    conn.close()
    return redirect(url_for('order_confirmation'))


@app.route('/order/confirmation')
def order_confirmation():
    order = session.get('last_order')
    if not order:
        return redirect(url_for('home'))
    return render_template('order_confirmation.html', order=order)


@app.route('/checkout/confirm', methods=['POST'])
def checkout_confirm():
    order_id = request.form.get('order_id')
    order = session.get('last_order')
    if not order or str(order.get('id')) != str(order_id):
        return redirect(url_for('home'))

    user = session.get('user')
    if user:
        try: from db import get_db_connection
        except ImportError: from backend.db import get_db_connection
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("INSERT INTO orders (email, total, payment_method, items_json) VALUES (?, ?, ?, ?)",
                  (user, order['total'], order['payment_method'], json.dumps(order['items'])))
        order['id'] = c.lastrowid
        session['last_order'] = order
        c.execute("DELETE FROM carts WHERE email = ?", (user,))
        conn.commit()
        conn.close()
    return redirect(url_for('order_confirmation'))


@app.route('/api/quick_upi', methods=['POST'])
def api_quick_upi():
    data = request.get_json() or {}
    upi_id = data.get('upi_id')
    merchant = data.get('merchant', 'SmartShop')
    amount = data.get('amount')
    try:
        amount_val = float(amount)
    except Exception:
        return jsonify({'error': 'invalid amount'}), 400

    if not upi_id or '@' not in upi_id:
        return jsonify({'error': 'invalid upi id'}), 400

    # create order but do not clear cart until confirmation
    items = session.get('cart') if session.get('cart') is not None else mock_cart_items
    order = {
        'id': session.get('order_counter', 1000) + 1,
        'items': items,
        'total': amount_val,
        'payment_method': 'upi'
    }
    session['last_order'] = order

    upi_uri = f"upi://pay?pa={urllib.parse.quote(upi_id)}&pn={urllib.parse.quote(merchant)}&am={urllib.parse.quote(str(amount_val))}&cu=INR"
    qr = f"https://api.qrserver.com/v1/create-qr-code/?size=300x300&data={urllib.parse.quote(upi_uri)}"

    return jsonify({'upi_uri': upi_uri, 'qr': qr, 'order_id': order['id']})


@app.route('/checkout/confirm', methods=['GET', 'POST'])
def checkout_confirm_get():
    if request.method == 'GET': order_id = request.args.get('order_id')
    else: order_id = request.form.get('order_id')
    order = session.get('last_order')
    if not order or str(order.get('id')) != str(order_id):
        return redirect(url_for('home'))

    user = session.get('user')
    if user:
        try: from db import get_db_connection
        except ImportError: from backend.db import get_db_connection
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("INSERT INTO orders (email, total, payment_method, items_json) VALUES (?, ?, ?, ?)",
                  (user, order['total'], order['payment_method'], json.dumps(order['items'])))
        order['id'] = c.lastrowid
        session['last_order'] = order
        c.execute("DELETE FROM carts WHERE email = ?", (user,))
        conn.commit()
        conn.close()
    return redirect(url_for('order_confirmation'))

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        identifier = request.form.get('email')
        # generate 6-digit OTP
        otp = str(random.randint(100000, 999999))
        expiry = int(time.time()) + 120  # 2 minutes
        session['pending_otp'] = {'code': otp, 'recipient': identifier, 'expires': expiry, 'last_sent': int(time.time()), 'resend_count': 0}

        # try sending via email if identifier looks like an email
        sent = False
        # send OTP (email or simulated SMS) using helper
        sent = False
        try:
            sent = send_otp_to_recipient(identifier, otp)
        except Exception as e:
            app.logger.error('Failed to send OTP: %s', e)
            sent = False

        return redirect(url_for('verify_otp'))
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.pop('user', None)
    return redirect(url_for("home"))


@app.route('/verify_otp', methods=['GET', 'POST'])
def verify_otp():
    pending = session.get('pending_otp')
    if request.method == 'POST':
        code = request.form.get('otp_code')
        if not pending:
            return redirect(url_for('login'))
        if int(time.time()) > pending.get('expires', 0):
            session.pop('pending_otp', None)
            return render_template('verify_otp.html', error='OTP expired. Please request a new one.', show_debug=app.debug, pending=None)
        if code == pending.get('code'):
            # success
            user_email = pending.get('recipient')
            try:
                try: from db import get_db_connection
                except ImportError: from backend.db import get_db_connection
                conn = get_db_connection()
                cursor = conn.cursor()
                cursor.execute("SELECT 1 FROM users WHERE email = ?", (user_email,))
                user_exists = cursor.fetchone() is not None
                if not user_exists:
                    session['show_new_user_quiz'] = True
                    conn.execute("INSERT OR IGNORE INTO users (email) VALUES (?)", (user_email,))
                conn.commit()
                conn.close()
            except Exception as e:
                print("DB insertion failed:", e)
                
            session['user'] = user_email
            session.pop('pending_otp', None)
            return redirect(url_for('index')) 
        else:
            return render_template('verify_otp.html', error='Invalid OTP. Please try again.', show_debug=app.debug, pending=pending)

    return render_template('verify_otp.html', show_debug=app.debug, pending=pending)


@app.route('/debug/last_otp')
def debug_last_otp():
    # Local dev helper: return last pending OTP from session (only available in debug mode)
    if not app.debug:
        return jsonify({'error': 'debug endpoint disabled'}), 403
    pending = session.get('pending_otp')
    if not pending:
        return jsonify({'error': 'no pending otp'}), 404
    return jsonify({'pending_otp': pending})


@app.route('/debug/set_pending_expiry', methods=['POST'])
def debug_set_pending_expiry():
    # Local dev helper: set pending OTP expiry seconds from now (debug-only)
    if not app.debug:
        return jsonify({'error': 'debug endpoint disabled'}), 403
    pending = session.get('pending_otp')
    if not pending:
        return jsonify({'error': 'no pending otp'}), 404
    try:
        seconds = int(request.args.get('seconds', '0'))
    except Exception:
        seconds = 0
    pending['expires'] = int(time.time()) + seconds
    session['pending_otp'] = pending
    return jsonify({'success': True, 'new_expires': pending['expires']})


def send_otp_to_recipient(identifier, otp):
    if identifier and '@' in identifier:
        try:
            msg = EmailMessage()
            msg['Subject'] = 'Your SmartShop OTP'
            msg['From'] = "pottapallisowmya@gmail.com"
            msg['To'] = identifier
            msg.set_content(f'Your SmartShop OTP is: {otp}. It will expire in 2 minutes.')

            server = smtplib.SMTP('smtp.gmail.com', 587)
            server.starttls()
            server.login("pottapallisowmya@gmail.com", "ivwb qqpt rurs atyq")
            server.send_message(msg)
            server.quit()

            print("✅ OTP sent to Gmail:", identifier)
            return True

        except Exception as e:
            print("❌ Email error:", e)
            return False

    return False


@app.route('/resend_otp', methods=['POST'])
def resend_otp():
    # Allow resending with cooldown and max attempts per session
    pending = session.get('pending_otp')
    if not pending:
        return jsonify({'error': 'no_pending_otp'}), 400

    now = int(time.time())
    last_sent = pending.get('last_sent', 0)
    resend_count = pending.get('resend_count', 0)

    COOLDOWN = 30
    MAX_RESENDS = 3

    seconds_since = now - last_sent
    if resend_count >= MAX_RESENDS:
        return jsonify({'error': 'max_resend_exceeded', 'attempts_left': 0}), 429
    if seconds_since < COOLDOWN:
        return jsonify({'error': 'cooldown', 'seconds_left': COOLDOWN - seconds_since, 'attempts_left': MAX_RESENDS - resend_count}), 429

    # generate a new OTP and invalidate previous
    new_otp = str(random.randint(100000, 999999))
    new_expires = now + 120
    pending['code'] = new_otp
    pending['expires'] = new_expires
    pending['last_sent'] = now
    pending['resend_count'] = resend_count + 1
    session['pending_otp'] = pending

    sent = send_otp_to_recipient(pending.get('recipient'), new_otp)
    if not sent:
        return jsonify({'error': 'send_failed'}), 500

    return jsonify({'success': True, 'seconds_left': 0, 'attempts_left': MAX_RESENDS - pending['resend_count']})


@app.route('/resend_status')
def resend_status():
    pending = session.get('pending_otp')
    if not pending:
        return jsonify({'has_pending': False})
    now = int(time.time())
    last_sent = pending.get('last_sent', 0)
    resend_count = pending.get('resend_count', 0)
    COOLDOWN = 30
    MAX_RESENDS = 3
    seconds_since = now - last_sent
    seconds_left = COOLDOWN - seconds_since if seconds_since < COOLDOWN else 0
    attempts_left = MAX_RESENDS - resend_count
    return jsonify({'has_pending': True, 'seconds_left': seconds_left if seconds_left>0 else 0, 'attempts_left': attempts_left})

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        return redirect(url_for("login"))
    return render_template("register.html")

# Legacy product_detail route has been merged into line 160

@app.route('/profile', methods=['GET', 'POST'])
def profile():
    if 'user' not in session:
        return redirect(url_for('login'))
    if request.method == 'POST':
        # Update editable fields in session
        name = request.form.get('name')
        phone = request.form.get('phone')
        address = request.form.get('address')
        if name:
            session['user_name'] = name
        if phone:
            session['phone'] = phone
        if address:
            session['address'] = address
        # After updating, redirect to GET to display updated info
        return redirect(url_for('profile'))
    return render_template('profile.html')

@app.route("/admin")
def admin():
    return render_template("admin.html", products=mock_products)


@app.route("/orders")
def orders():
    user = session.get('user')
    if not user: return redirect(url_for('login'))
    
    try: from db import get_db_connection
    except ImportError: from backend.db import get_db_connection
    conn = get_db_connection()
    rows = conn.execute("SELECT * FROM orders WHERE email = ? ORDER BY created_at DESC", (user,)).fetchall()
    orders = []
    for r in rows:
        orders.append({
            'id': r['id'],
            'total': r['total'],
            'payment_method': r['payment_method'],
            'date': r['created_at'],
            'items': json.loads(r['items_json'])
        })
    conn.close()
    return render_template('orders.html', orders=orders)


@app.route("/membership")
def membership():
    logged_in = 'user' in session
    membership_benefits = [
        "Free delivery on orders over ₹500",
        "Exclusive member deals and coupons",
        "Early access to sales and new products"
    ]
    payment_methods = [
        {"label": "Visa **** 4242", "expiry": "12/24"},
        {"label": "Mastercard **** 1111", "expiry": "11/25"}
    ]
    return render_template('membership.html', benefits=membership_benefits, payment_methods=payment_methods, logged_in=logged_in)


@app.route('/api/cart/add', methods=['POST'])
def api_cart_add():
    data = request.get_json() or {}
    try: product_id = int(data.get('product_id'))
    except Exception: return jsonify({'error': 'invalid product id'}), 400
    qty = int(data.get('quantity', 1)) if data.get('quantity') else 1
    
    user = session.get('user')
    if not user: return jsonify({'error': 'login_required'}), 401

    try: from db import get_db_connection
    except ImportError: from backend.db import get_db_connection
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT quantity FROM carts WHERE email = ? AND product_id = ?", (user, product_id))
    row = c.fetchone()
    if row:
        c.execute("UPDATE carts SET quantity = quantity + ? WHERE email = ? AND product_id = ?", (qty, user, product_id))
    else:
        c.execute("INSERT INTO carts (email, product_id, quantity) VALUES (?, ?, ?)", (user, product_id, qty))
    conn.commit()
    r = conn.execute("SELECT SUM(quantity) FROM carts WHERE email = ?", (user,)).fetchone()[0]
    conn.close()
    return jsonify({'success': True, 'total_items': r or 0})


@app.route('/api/cart/count')
def api_cart_count():
    user = session.get('user')
    if not user:
        return jsonify({'total_items': 0})
    try: from db import get_db_connection
    except ImportError: from backend.db import get_db_connection
    conn = get_db_connection()
    r = conn.execute("SELECT SUM(quantity) FROM carts WHERE email = ?", (user,)).fetchone()[0]
    conn.close()
    return jsonify({'total_items': r or 0})

if __name__ == "__main__":
    app.run(debug=True, port=5000)


# Hot reload trigger

# Hot reload trigger for people removal
