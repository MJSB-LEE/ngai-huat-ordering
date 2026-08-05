import streamlit as st
import streamlit.components.v1 as components
import sqlite3
import urllib.parse
import base64
import io
import pandas as pd
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from PIL import Image

try:
    from streamlit_sortables import sort_items
except ImportError:
    st.error("Please install streamlit-sortables via: pip install streamlit-sortables")

st.set_page_config(
    page_title="Grocery POS & Ordering System", 
    page_icon="🏪", 
    layout="wide",
    initial_sidebar_state="expanded"
)

ALLOWED_IMAGE_EXTS = ["avif", "webp", "jpg", "jpeg", "png", "gif", "bmp", "tiff", "ico"]

MOBILE_CSS = """
<style>
    footer {visibility: hidden;}
    
    .block-container {
        padding-top: 1rem !important;
        padding-bottom: 5rem !important;
        padding-left: 0.8rem !important;
        padding-right: 0.8rem !important;
    }

    div[data-testid="stVerticalBlockBorderWrapper"] {
        border-radius: 12px !important;
        box-shadow: 0 2px 6px rgba(0,0,0,0.15) !important;
        margin-bottom: 8px !important;
    }

    .stButton button {
        border-radius: 10px !important;
        min-height: 44px !important;
        font-weight: bold !important;
    }
    
    .shop-header {
        background-color: #1e1e1e;
        border-radius: 12px;
        padding: 16px;
        text-align: center;
        margin-bottom: 16px;
        border: 1px solid #333;
    }
    .shop-title {
        color: #f1c40f;
        font-size: 22px;
        font-weight: bold;
        margin: 0;
    }
    .shop-location {
        color: #bdc3c7;
        font-size: 14px;
        margin-top: 4px;
    }
</style>
"""

LIVE_SEARCH_JS = """
<script>
    const doc = window.parent.document;
    const inputs = doc.querySelectorAll('input[aria-label="Search Item Name or Code"]');
    inputs.forEach(input => {
        if (!input.dataset.liveSearchBound) {
            input.dataset.liveSearchBound = "true";
            input.addEventListener('input', function() {
                input.dispatchEvent(new Event('change', { bubbles: true }));
            });
        }
    });
</script>
"""

def image_to_base64(uploaded_file):
    if uploaded_file is not None:
        try:
            img = Image.open(uploaded_file)
            if img.mode in ("RGBA", "P"):
                img = img.convert("RGBA")
                buffered = io.BytesIO()
                img.save(buffered, format="PNG")
                mime_type = "image/png"
            else:
                img = img.convert("RGB")
                buffered = io.BytesIO()
                img.save(buffered, format="JPEG")
                mime_type = "image/jpeg"

            base64_str = base64.b64encode(buffered.getvalue()).decode()
            return f"data:{mime_type};base64,{base64_str}"
        except Exception as e:
            st.error(f"Failed to process image: {e}")
            return None
    return None

def init_db():
    conn = sqlite3.connect("pos_inventory.db")
    c = conn.cursor()
    
    c.execute('''
        CREATE TABLE IF NOT EXISTS menu (
            code TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            category TEXT NOT NULL,
            price REAL NOT NULL,
            image_data TEXT
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS cashiers (
            name TEXT PRIMARY KEY,
            sort_order INTEGER DEFAULT 0,
            email TEXT DEFAULT '',
            smtp_password TEXT DEFAULT ''
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS locations (
            name TEXT PRIMARY KEY,
            sort_order INTEGER DEFAULT 0
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    ''')

    c.execute("PRAGMA table_info(cashiers)")
    cols = [col[1] for col in c.fetchall()]
    if "sort_order" not in cols:
        c.execute("ALTER TABLE cashiers ADD COLUMN sort_order INTEGER DEFAULT 0")
    if "email" not in cols:
        c.execute("ALTER TABLE cashiers ADD COLUMN email TEXT DEFAULT ''")
    if "smtp_password" not in cols:
        c.execute("ALTER TABLE cashiers ADD COLUMN smtp_password TEXT DEFAULT ''")

    c.execute("PRAGMA table_info(locations)")
    cols_loc = [col[1] for col in c.fetchall()]
    if "sort_order" not in cols_loc:
        c.execute("ALTER TABLE locations ADD COLUMN sort_order INTEGER DEFAULT 0")

    c.execute("SELECT COUNT(*) FROM cashiers")
    if c.fetchone()[0] == 0:
        c.executemany("INSERT INTO cashiers (name, sort_order, email, smtp_password) VALUES (?, ?, ?, ?)", [
            ("BEBELYN", 1, "", ""),
            ("CASHIER 01", 2, "", ""),
            ("ADMIN", 3, "", "")
        ])
        
    c.execute("SELECT COUNT(*) FROM locations")
    if c.fetchone()[0] == 0:
        c.executemany("INSERT INTO locations VALUES (?, ?)", [("MAIN BRANCH", 1), ("STYLAND", 2)])

    c.execute('''
        CREATE TABLE IF NOT EXISTS order_counter (
            yymm TEXT PRIMARY KEY,
            last_seq INTEGER NOT NULL
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS orders (
            order_no TEXT PRIMARY KEY,
            customer_name TEXT,
            location TEXT,
            cashier TEXT,
            items_summary TEXT,
            total_amount REAL,
            status TEXT,
            created_at TEXT,
            completed_at TEXT,
            cancelled_at TEXT,
            cancel_reason TEXT
        )
    ''')
    conn.commit()

    c.execute("SELECT COUNT(*) FROM menu")
    if c.fetchone()[0] == 0:
        default_items = [
            ("R01", "Rambutan Rice 10kg", "Rice & Flour", 38.00, "https://images.unsplash.com/photo-1586201375761-83865001e31c?w=150"),
            ("M01", "Cooking Oil 5kg", "Oils & Spices", 33.50, "https://images.unsplash.com/photo-1620706857370-e1b9770e8bb1?w=150"),
            ("G01", "Fine Sugar 1kg", "Pantry Essentials", 2.85, "https://images.unsplash.com/photo-1581441363689-1f3c3c414635?w=150"),
            ("D01", "Coca-Cola 1.5L", "Beverages", 4.20, "https://images.unsplash.com/photo-1622483767028-3f66f32aef97?w=150")
        ]
        c.executemany("INSERT INTO menu VALUES (?, ?, ?, ?, ?)", default_items)
        conn.commit()
    conn.close()

def get_setting(key, default_value=""):
    conn = sqlite3.connect("pos_inventory.db")
    c = conn.cursor()
    c.execute("SELECT value FROM settings WHERE key = ?", (key,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else default_value

def save_setting(key, value):
    conn = sqlite3.connect("pos_inventory.db")
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, str(value).strip()))
    conn.commit()
    conn.close()

def get_cashiers():
    conn = sqlite3.connect("pos_inventory.db")
    c = conn.cursor()
    c.execute("SELECT name FROM cashiers ORDER BY sort_order ASC, name ASC")
    rows = [r[0] for r in c.fetchall()]
    conn.close()
    return rows if rows else ["DEFAULT CASHIER"]

def get_cashier_details(name):
    conn = sqlite3.connect("pos_inventory.db")
    c = conn.cursor()
    c.execute("SELECT email, smtp_password FROM cashiers WHERE name = ?", (name,))
    row = c.fetchone()
    conn.close()
    return row if row else ("", "")

def save_cashiers_order(ordered_names):
    conn = sqlite3.connect("pos_inventory.db")
    c = conn.cursor()
    for index, name in enumerate(ordered_names):
        c.execute("UPDATE cashiers SET sort_order = ? WHERE name = ?", (index + 1, name))
    conn.commit()
    conn.close()

def add_cashier(name, email="", smtp_password=""):
    conn = sqlite3.connect("pos_inventory.db")
    c = conn.cursor()
    c.execute("SELECT COALESCE(MAX(sort_order), 0) + 1 FROM cashiers")
    new_order = c.fetchone()[0]
    c.execute("INSERT OR REPLACE INTO cashiers (name, sort_order, email, smtp_password) VALUES (?, ?, ?, ?)", 
              (name.upper().strip(), new_order, email.strip(), smtp_password.strip()))
    conn.commit()
    conn.close()

def update_cashier_details(old_name, new_name, email, smtp_password):
    conn = sqlite3.connect("pos_inventory.db")
    c = conn.cursor()
    c.execute("SELECT sort_order FROM cashiers WHERE name = ?", (old_name,))
    row = c.fetchone()
    old_order = row[0] if row else 1
    c.execute("DELETE FROM cashiers WHERE name = ?", (old_name,))
    c.execute("INSERT OR REPLACE INTO cashiers (name, sort_order, email, smtp_password) VALUES (?, ?, ?, ?)", 
              (new_name.upper().strip(), old_order, email.strip(), smtp_password.strip()))
    conn.commit()
    conn.close()

def delete_cashier(name):
    conn = sqlite3.connect("pos_inventory.db")
    c = conn.cursor()
    c.execute("DELETE FROM cashiers WHERE name = ?", (name,))
    conn.commit()
    conn.close()

def get_locations():
    conn = sqlite3.connect("pos_inventory.db")
    c = conn.cursor()
    c.execute("SELECT name FROM locations ORDER BY sort_order ASC, name ASC")
    rows = [r[0] for r in c.fetchall()]
    conn.close()
    return rows if rows else ["MAIN BRANCH"]

def save_locations_order(ordered_names):
    conn = sqlite3.connect("pos_inventory.db")
    c = conn.cursor()
    for index, name in enumerate(ordered_names):
        c.execute("UPDATE locations SET sort_order = ? WHERE name = ?", (index + 1, name))
    conn.commit()
    conn.close()

def add_location(name):
    conn = sqlite3.connect("pos_inventory.db")
    c = conn.cursor()
    c.execute("SELECT COALESCE(MAX(sort_order), 0) + 1 FROM locations")
    new_order = c.fetchone()[0]
    c.execute("INSERT OR REPLACE INTO locations (name, sort_order) VALUES (?, ?)", (name.upper().strip(), new_order))
    conn.commit()
    conn.close()

def update_location_name(old_name, new_name):
    conn = sqlite3.connect("pos_inventory.db")
    c = conn.cursor()
    c.execute("SELECT sort_order FROM locations WHERE name = ?", (old_name,))
    row = c.fetchone()
    old_order = row[0] if row else 1
    c.execute("DELETE FROM locations WHERE name = ?", (old_name,))
    c.execute("INSERT OR REPLACE INTO locations (name, sort_order) VALUES (?, ?)", (new_name.upper().strip(), old_order))
    conn.commit()
    conn.close()

def delete_location(name):
    conn = sqlite3.connect("pos_inventory.db")
    c = conn.cursor()
    c.execute("DELETE FROM locations WHERE name = ?", (name,))
    conn.commit()
    conn.close()

def get_next_order_number():
    current_yymm = datetime.now().strftime("%y%m")
    conn = sqlite3.connect("pos_inventory.db")
    c = conn.cursor()
    c.execute("SELECT last_seq FROM order_counter WHERE yymm = ?", (current_yymm,))
    row = c.fetchone()
    
    if row:
        next_seq = row[0] + 1
    else:
        next_seq = 1
        
    order_num = f"{current_yymm}-{next_seq:04d}"
    conn.close()
    return order_num, current_yymm, next_seq

def save_new_order(order_no, customer, location, cashier, items_summary, total_amount, yymm, seq):
    conn = sqlite3.connect("pos_inventory.db")
    c = conn.cursor()
    created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    c.execute("INSERT OR REPLACE INTO orders VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", 
              (order_no, customer, location, cashier, items_summary, total_amount, "Pending", created_at, "", "", ""))
    c.execute("INSERT OR REPLACE INTO order_counter VALUES (?, ?)", (yymm, seq))
    conn.commit()
    conn.close()

def get_orders_by_status(status, month_filter=None):
    conn = sqlite3.connect("pos_inventory.db")
    c = conn.cursor()
    if month_filter and month_filter != "All Months":
        query = "SELECT order_no, customer_name, location, cashier, items_summary, total_amount, created_at, completed_at, cancelled_at, cancel_reason FROM orders WHERE status = ? AND strftime('%Y-%m', created_at) = ? ORDER BY created_at DESC"
        c.execute(query, (status, month_filter))
    else:
        query = "SELECT order_no, customer_name, location, cashier, items_summary, total_amount, created_at, completed_at, cancelled_at, cancel_reason FROM orders WHERE status = ? ORDER BY created_at DESC"
        c.execute(query, (status,))
    rows = c.fetchall()
    conn.close()
    return rows

def get_available_order_months():
    conn = sqlite3.connect("pos_inventory.db")
    c = conn.cursor()
    c.execute("SELECT DISTINCT strftime('%Y-%m', created_at) FROM orders WHERE created_at IS NOT NULL ORDER BY created_at DESC")
    rows = c.fetchall()
    conn.close()
    months = [r[0] for r in rows if r[0]]
    current_m = datetime.now().strftime("%Y-%m")
    if current_m not in months:
        months.insert(0, current_m)
    return ["All Months"] + months

def get_menu_items():
    conn = sqlite3.connect("pos_inventory.db")
    c = conn.cursor()
    c.execute("SELECT code, name, category, price, image_data FROM menu")
    rows = c.fetchall()
    conn.close()
    
    menu = {}
    for row in rows:
        menu[row[0]] = {
            "name": row[1],
            "category": row[2],
            "price": row[3],
            "image": row[4]
        }
    return menu

def add_or_update_menu_item(code, name, category, price, image_data):
    conn = sqlite3.connect("pos_inventory.db")
    c = conn.cursor()
    if image_data is None:
        c.execute("SELECT image_data FROM menu WHERE code = ?", (code,))
        row = c.fetchone()
        if row:
            image_data = row[0]

    c.execute("INSERT OR REPLACE INTO menu VALUES (?, ?, ?, ?, ?)", (code, name, category, price, image_data))
    conn.commit()
    conn.close()

def delete_menu_item(code):
    conn = sqlite3.connect("pos_inventory.db")
    c = conn.cursor()
    c.execute("DELETE FROM menu WHERE code = ?", (code,))
    conn.commit()
    conn.close()

def update_order_status(order_no, status, cancel_reason=""):
    conn = sqlite3.connect("pos_inventory.db")
    c = conn.cursor()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if status == "Completed":
        c.execute("UPDATE orders SET status = ?, completed_at = ? WHERE order_no = ?", (status, now_str, order_no))
    elif status == "Cancelled":
        c.execute("UPDATE orders SET status = ?, cancelled_at = ?, cancel_reason = ? WHERE order_no = ?", (status, now_str, cancel_reason, order_no))
    conn.commit()
    conn.close()

init_db()

# Session States
if "cart" not in st.session_state:
    st.session_state.cart = {}
if "editing_code" not in st.session_state:
    st.session_state.editing_code = None

query_params = st.query_params
url_admin = query_params.get("admin", "false").lower() == "true"

if "is_admin" not in st.session_state:
    st.session_state.is_admin = url_admin
elif url_admin:
    st.session_state.is_admin = True

st.sidebar.markdown("### 🔒 Staff Authentication")
if not st.session_state.is_admin:
    pin_input = st.sidebar.text_input("Admin PIN", type="password", placeholder="1234")
    if st.sidebar.button("Unlock Admin"):
        if pin_input == "1234":
            st.session_state.is_admin = True
            st.sidebar.success("Unlocked Admin Access!")
            st.rerun()
        else:
            st.sidebar.error("Incorrect PIN!")
else:
    st.sidebar.success("🔓 Admin Mode Active")
    if st.sidebar.button("🔒 Lock Admin Access"):
        st.session_state.is_admin = False
        st.query_params.clear()
        st.rerun()

# Load General Settings from DB
company_name_setting = get_setting("company_name", "SYARIKAT NGAI HUAT SDN BHD")
active_branch_setting = get_setting("active_branch_location", "")
img_size = int(get_setting("item_image_width", "100"))

# ==========================================
# CLIENT HP SELF-ORDERING PORTAL
# ==========================================
if not st.session_state.is_admin:
    st.markdown(MOBILE_CSS, unsafe_allow_html=True)
    components.html(LIVE_SEARCH_JS, height=0)
    
    menu_data = get_menu_items()
    active_locations = get_locations()
    
    # Selected location from settings or fallback to first available location
    display_location = active_branch_setting if active_branch_setting in active_locations else (active_locations[0] if active_locations else "MAIN BRANCH")
    
    st.markdown(f"""
        <div class="shop-header">
            <div class="shop-title">{company_name_setting}</div>
            <div class="shop-location">📍 Branch Location: <strong>{display_location}</strong></div>
        </div>
    """, unsafe_allow_html=True)

    with st.container(border=True):
        client_name = st.text_input("Customer Name *", key="hp_cust_name", placeholder="e.g. Mr. Tan")

    st.markdown("##### 🔎 Search & Filter Items")
    search_query = st.text_input(
        "Search Item Name or Code", 
        key="live_search_key",
        placeholder="Type item name or code...", 
        label_visibility="collapsed"
    )
    
    categories = ["All"] + sorted(list(set(item["category"] for item in menu_data.values())))
    selected_category = st.radio("Category:", categories, horizontal=True)
    
    filtered_menu = {}
    for code, details in menu_data.items():
        matches_cat = (selected_category == "All" or details["category"] == selected_category)
        matches_search = (
            not search_query.strip() or 
            search_query.lower() in details["name"].lower() or 
            search_query.lower() in code.lower()
        )
        if matches_cat and matches_search:
            filtered_menu[code] = details

    st.markdown("##### 📦 Item Catalog")
    if not filtered_menu:
        st.warning("No items match your search or selected category.")
    else:
        for code, item in filtered_menu.items():
            with st.container(border=True):
                col_img, col_detail = st.columns([1, 2.2])
                with col_img:
                    if item["image"]:
                        st.image(item["image"], use_container_width=True)
                with col_detail:
                    st.markdown(f"**[{code}] {item['name']}**")
                    st.markdown(f"<span style='color:#27ae60;font-weight:bold;'>RM {item['price']:.2f}</span>", unsafe_allow_html=True)
                    
                    curr_qty = st.session_state.cart.get(code, 0)
                    if curr_qty == 0:
                        if st.button("➕ Add", key=f"hp_add_{code}", use_container_width=True):
                            st.session_state.cart[code] = 1
                            st.rerun()
                    else:
                        q_c1, q_c2, q_c3 = st.columns([1, 1, 1])
                        with q_c1:
                            if st.button("➖", key=f"hp_minus_{code}", use_container_width=True):
                                st.session_state.cart[code] -= 1
                                if st.session_state.cart[code] <= 0:
                                    del st.session_state.cart[code]
                                st.rerun()
                        with q_c2:
                            st.markdown(f"<h4 style='text-align:center;margin:0;'>{curr_qty}</h4>", unsafe_allow_html=True)
                        with q_c3:
                            if st.button("➕", key=f"hp_plus_{code}", use_container_width=True):
                                st.session_state.cart[code] += 1
                                st.rerun()

    st.write("---")
    st.markdown("### 🛒 Your Order Slip")
    current_order_no, current_yymm, current_seq = get_next_order_number()
    
    if not st.session_state.cart:
        st.info("Your cart is empty. Select items above to start ordering.")
    else:
        total_amount = 0.0
        items_str_list = []
        
        for code, qty in list(st.session_state.cart.items()):
            if code in menu_data:
                item = menu_data[code]
                subtotal = item["price"] * qty
                total_amount += subtotal
                items_str_list.append(f"[{code}] {item['name']} x{qty}")
                
                st.write(f"• **{item['name']}** x{qty} = **RM {subtotal:.2f}**")
        
        st.markdown(f"### **Total Amount: RM {total_amount:.2f}**")
        customer_comment = st.text_area("Remarks / Notes (Optional)", placeholder="e.g. Packing requests...")
        
        items_summary_str = ", ".join(items_str_list)

        col_sub, col_rst = st.columns([3, 1])
        with col_sub:
            if st.button("🚀 Confirm & Submit Order", type="primary", use_container_width=True):
                if not client_name.strip():
                    st.error("⚠️ Please fill in Customer Name!")
                else:
                    save_new_order(current_order_no, client_name.strip(), display_location, 
                                   "CLIENT MOBILE", items_summary_str, total_amount, current_yymm, current_seq)
                    
                    st.balloons()
                    st.success(f"🎉 Order `{current_order_no}` placed successfully!")
                    st.session_state.cart = {}
                    st.rerun()
        with col_rst:
            if st.button("🗑️ Clear", use_container_width=True):
                st.session_state.cart = {}
                st.rerun()

# ==========================================
# STAFF POS & ADMIN MANAGEMENT VIEW
# ==========================================
else:
    st.title(f"🏪 {company_name_setting} - Staff POS & Admin")

    tab_pos, tab_process, tab_item_out, tab_manage, tab_settings = st.tabs([
        "🛒 Sales Counter", 
        "⏳ Processing Orders", 
        "📊 Monthly Item Out Report", 
        "📦 Add / Manage Items", 
        "⚙️ System Settings"
    ])

    with tab_pos:
        st.subheader("Sales Counter (Staff Mode)")
        st.info("Staff POS interface for cashier desktop/tablet usage.")

    with tab_process:
        c_head, c_month_select = st.columns([3, 1.2])
        with c_head:
            st.subheader("📊 Processing Orders Management")
        with c_month_select:
            month_options = get_available_order_months()
            selected_month = st.selectbox("📅 Filter by Month:", month_options, index=0)

        pending_orders = get_orders_by_status("Pending", selected_month)
        completed_orders = get_orders_by_status("Completed", selected_month)
        cancelled_orders = get_orders_by_status("Cancelled", selected_month)

        subtotal_pending = sum(o[5] for o in pending_orders)
        subtotal_completed = sum(o[5] for o in completed_orders)
        subtotal_cancelled = sum(o[5] for o in cancelled_orders)

        m1, m2, m3 = st.columns(3)
        with m1:
            st.metric("Pending Orders Value", f"RM {subtotal_pending:.2f}", f"{len(pending_orders)} pending")
        with m2:
            st.metric("Total Completed Revenue", f"RM {subtotal_completed:.2f}", f"{len(completed_orders)} completed")
        with m3:
            st.metric("Total Cancelled Amount", f"RM {subtotal_cancelled:.2f}", f"{len(cancelled_orders)} cancelled")

        st.write("---")
        
        proc_tab1, proc_tab2 = st.tabs([f"⏳ Active Pending Orders ({len(pending_orders)})", "📜 Order History"])

        with proc_tab1:
            if not pending_orders:
                st.info(f"No pending orders for {selected_month}.")
            else:
                for order in pending_orders:
                    order_no, cust_name, loc, cashier, items_str, total_amt, created_at, _, _, _ = order
                    
                    with st.container(border=True):
                        col1, col2, col3 = st.columns([2.5, 3, 1.8])
                        with col1:
                            st.markdown(f"🏷️ **Order No:** `{order_no}`")
                            st.write(f"👤 **Customer:** {cust_name}")
                            st.caption(f"📍 Location: {loc} | Cashier: {cashier}")
                            st.caption(f"🕒 **Created Time:** {created_at}")
                        with col2:
                            st.write("🛒 **Summary:**")
                            st.write(items_str)
                            st.markdown(f"💰 **Total Amount:** **RM {total_amt:.2f}**")

                        with col3:
                            st.write(" ")
                            if st.button("✅ Complete Order", key=f"complete_{order_no}", use_container_width=True, type="primary"):
                                update_order_status(order_no, "Completed")
                                st.success(f"Order {order_no} completed!")
                                st.rerun()

                            if st.button("❌ Cancel Order", key=f"cancel_btn_{order_no}", use_container_width=True):
                                update_order_status(order_no, "Cancelled", "Cancelled by Staff")
                                st.success(f"Order {order_no} cancelled!")
                                st.rerun()

        with proc_tab2:
            hist_tab1, hist_tab2 = st.tabs(["✅ Completed Orders", "❌ Cancelled Orders"])
            
            with hist_tab1:
                if not completed_orders:
                    st.caption(f"No completed orders for {selected_month}.")
                else:
                    comp_data = [[o[0], o[1], o[2], o[3], o[4], o[5], o[6], o[7]] for o in completed_orders]
                    completed_df = pd.DataFrame(
                        comp_data, 
                        columns=["Order No", "Customer", "Location", "Cashier", "Items Summary", "Total (RM)", "Created Time", "Completed Time"]
                    )
                    st.dataframe(completed_df, use_container_width=True)

            with hist_tab2:
                if not cancelled_orders:
                    st.caption(f"No cancelled orders for {selected_month}.")
                else:
                    canc_data = [[o[0], o[1], o[2], o[3], o[4], o[5], o[9], o[6], o[8]] for o in cancelled_orders]
                    cancelled_df = pd.DataFrame(
                        canc_data, 
                        columns=["Order No", "Customer", "Location", "Cashier", "Items Summary", "Total (RM)", "Cancellation Reason", "Created Time", "Cancelled Time"]
                    )
                    st.dataframe(cancelled_df, use_container_width=True)

    with tab_item_out:
        st.subheader("📊 Monthly Item Out Quantity Summary (AutoCount Cash Sales)")
        cs_file = st.file_uploader("Upload AutoCount Cash Sales File", type=["xlsx", "csv"], key="cs_report_uploader")
        if cs_file:
            try:
                df_cs = pd.read_csv(cs_file) if cs_file.name.endswith(".csv") else pd.read_excel(cs_file)
                st.dataframe(df_cs.head(5), use_container_width=True)
                cols = df_cs.columns.tolist()
                c1, c2, c3, c4 = st.columns(4)
                with c1:
                    col_item_code = st.selectbox("Item Code Column:", cols, index=0)
                with c2:
                    col_item_desc = st.selectbox("Description Column:", cols, index=1 if len(cols)>1 else 0)
                with c3:
                    col_qty = st.selectbox("Quantity Column:", cols, index=2 if len(cols)>2 else 0)
                with c4:
                    col_date = st.selectbox("Date Column (Optional):", ["(No Date Column)"] + cols, index=0)

                df_cs[col_qty] = pd.to_numeric(df_cs[col_qty], errors='coerce').fillna(0)
                summary_df = df_cs.groupby([col_item_code, col_item_desc], as_index=False)[col_qty].sum()
                summary_df.columns = ["Item Code", "Description", "Total Out Quantity"]
                st.dataframe(summary_df.sort_values(by="Total Out Quantity", ascending=False), use_container_width=True)
            except Exception as e:
                st.error(f"Error reading file: {e}")

    # --- TAB 4: ADD / EDIT / MANAGE INVENTORY ---
    with tab_manage:
        current_menu = get_menu_items()
        col_forms, col_list = st.columns([2, 3])
        
        with col_forms:
            mode = st.radio("Action:", ["➕ Add New Item", "✏️ Edit / Update Item", "📥 Import from AutoCount"], key="radio_manage_mode", horizontal=True)
            
            if mode == "➕ Add New Item":
                st.subheader("➕ Add New Item")
                with st.form("add_item_form", clear_on_submit=True):
                    new_code = st.text_input("Item Code (SKU)").upper().strip()
                    new_name = st.text_input("Item Name")
                    new_cat = st.text_input("Category").capitalize().strip()
                    new_price = st.number_input("Price (RM)", min_value=0.0, step=0.10, value=3.00)
                    uploaded_file = st.file_uploader("Upload Image", type=ALLOWED_IMAGE_EXTS)
                    
                    if st.form_submit_button("Save New Item"):
                        if new_code and new_name and new_cat:
                            add_or_update_menu_item(new_code, new_name, new_cat, new_price, image_to_base64(uploaded_file))
                            st.success(f"Saved [{new_code}] {new_name}")
                            st.rerun()

            elif mode == "✏️ Edit / Update Item":
                st.subheader("✏️ Edit Item")
                if not current_menu:
                    st.info("No items in inventory to edit.")
                else:
                    item_options = {f"[{code}] {details['name']}": code for code, details in current_menu.items()}
                    item_keys = list(item_options.keys())
                    
                    selected_idx = 0
                    if st.session_state.editing_code:
                        for i, (k, v) in enumerate(item_options.items()):
                            if v == st.session_state.editing_code:
                                selected_idx = i
                                break

                    selected_label = st.selectbox("Select Item to Edit:", item_keys, index=selected_idx)
                    selected_code = item_options[selected_label]
                    selected_item = current_menu[selected_code]

                    with st.form("edit_item_form"):
                        st.write(f"Editing Item Code: **{selected_code}**")
                        edit_name = st.text_input("Item Name", value=selected_item["name"])
                        edit_cat = st.text_input("Category", value=selected_item["category"])
                        edit_price = st.number_input("Price (RM)", value=float(selected_item["price"]))
                        edit_uploaded_file = st.file_uploader("Upload New Image (Optional)", type=ALLOWED_IMAGE_EXTS)
                        
                        if st.form_submit_button("💾 Save Changes"):
                            img_data = image_to_base64(edit_uploaded_file) if edit_uploaded_file else None
                            add_or_update_menu_item(selected_code, edit_name, edit_cat, edit_price, img_data)
                            st.success(f"Updated item [{selected_code}] successfully!")
                            st.rerun()

                    st.write("---")
                    if st.button(f"🗑️ Delete Item [{selected_code}]", use_container_width=True):
                        delete_menu_item(selected_code)
                        st.session_state.editing_code = None
                        st.success(f"Deleted item [{selected_code}]!")
                        st.rerun()

            else:
                st.subheader("📥 Import Inventory from AutoCount")
                st.caption("Upload AutoCount Excel or CSV file.")

        with col_list:
            st.subheader("Current Inventory Items")
            for code, details in current_menu.items():
                with st.container(border=True):
                    c_img, c_info, c_edit = st.columns([1.5, 3, 1.2])
                    with c_img:
                        if details["image"]:
                            st.image(details["image"], width=img_size)
                    with c_info:
                        st.write(f"**[{code}] {details['name']}**")
                        st.caption(f"RM {details['price']:.2f} | Category: {details['category']}")
                    with c_edit:
                        if st.button("✏️ Edit", key=f"manage_{code}", use_container_width=True):
                            st.session_state.editing_code = code
                            st.rerun()

    # --- TAB 5: SYSTEM CONFIGURATION, COMPANY & LOCATION SETTINGS ---
    with tab_settings:
        st.subheader("⚙️ System Configuration & General Settings")
        
        # COMPANY NAME & ACTIVE BRANCH LOCATION SETTINGS
        with st.container(border=True):
            st.markdown("### 🏢 Company & Active Branch Settings")
            
            new_comp_name = st.text_input("Company Name", value=company_name_setting)
            
            all_locs = get_locations()
            current_loc_idx = all_locs.index(active_branch_setting) if active_branch_setting in all_locs else 0
            new_active_loc = st.selectbox("Active Client Portal Branch Location", all_locs, index=current_loc_idx)
            
            if st.button("💾 Save Company & Branch Settings"):
                save_setting("company_name", new_comp_name.strip())
                save_setting("active_branch_location", new_active_loc)
                st.success("Company Name and Active Branch updated successfully!")
                st.rerun()

        st.write("---")

        with st.container(border=True):
            st.markdown("### 🖼️ Catalog Image Display Size")
            new_size = st.slider("Product Image Width (pixels)", 50, 300, img_size, 10)
            if st.button("💾 Save Image Size"):
                save_setting("item_image_width", str(new_size))
                st.success("Saved image display size!")
                st.rerun()

        st.write("---")

        col_users, col_locs = st.columns(2)
        
        # Cashiers & Email Credentials Management
        with col_users:
            with st.container(border=True):
                st.markdown("### 👤 Cashiers / Staff Emails")
                
                with st.form("add_cashier_form", clear_on_submit=True):
                    st.caption("Add cashier with sending Gmail account & App Password:")
                    new_c_name = st.text_input("Cashier Name *").upper().strip()
                    new_c_email = st.text_input("Gmail Address")
                    new_c_pass = st.text_input("Gmail App Password (16 chars)", type="password")
                    
                    if st.form_submit_button("➕ Add Cashier"):
                        if new_c_name:
                            add_cashier(new_c_name, new_c_email, new_c_pass)
                            st.success(f"Added cashier {new_c_name}")
                            st.rerun()

                st.write("---")
                st.markdown("**Drag to Reorder Cashiers:**")
                current_cashiers_list = get_cashiers()
                sorted_cashiers = sort_items(current_cashiers_list, key="sort_cashiers")
                if st.button("💾 Save Cashier Order", use_container_width=True):
                    save_cashiers_order(sorted_cashiers)
                    st.rerun()

                st.write("---")
                st.markdown("**Manage Selected Cashier:**")
                selected_cashier_to_edit = st.selectbox("Select Cashier to Edit/Delete:", current_cashiers_list, key="sel_cashier_edit")
                curr_email, curr_pass = get_cashier_details(selected_cashier_to_edit)
                
                with st.form("form_manage_selected_cashier"):
                    edited_c_name = st.text_input("Cashier Name", value=selected_cashier_to_edit)
                    edited_c_email = st.text_input("Cashier Gmail Address", value=curr_email)
                    edited_c_pass = st.text_input("Cashier Gmail App Password", value=curr_pass, type="password")
                    
                    c_c_save, c_c_del = st.columns(2)
                    with c_c_save:
                        if st.form_submit_button("💾 Save Credentials"):
                            if edited_c_name.strip():
                                update_cashier_details(selected_cashier_to_edit, edited_c_name, edited_c_email, edited_c_pass)
                                st.success(f"Updated cashier {edited_c_name.upper()}")
                                st.rerun()
                    with c_c_del:
                        if st.form_submit_button("🗑️ Delete Cashier"):
                            delete_cashier(selected_cashier_to_edit)
                            st.success(f"Deleted cashier {selected_cashier_to_edit}")
                            st.rerun()

        # Store Locations / Branches Management
        with col_locs:
            with st.container(border=True):
                st.markdown("### 📍 Store Locations")
                
                with st.form("add_location_form", clear_on_submit=True):
                    new_loc = st.text_input("Branch Name *").upper().strip()
                    if st.form_submit_button("➕ Add Location"):
                        if new_loc:
                            add_location(new_loc)
                            st.success(f"Added location {new_loc}")
                            st.rerun()

                st.write("---")
                st.markdown("**Drag to Reorder Locations:**")
                current_locations_list = get_locations()
                sorted_locations = sort_items(current_locations_list, key="sort_locations")
                if st.button("💾 Save Location Order", use_container_width=True):
                    save_locations_order(sorted_locations)
                    st.rerun()

                st.write("---")
                st.markdown("**Manage Selected Location:**")
                selected_location_to_edit = st.selectbox("Select Location to Edit/Delete:", current_locations_list, key="sel_loc_edit")
                
                with st.form("form_manage_selected_location"):
                    edited_l_name = st.text_input("Location Name", value=selected_location_to_edit)
                    c_l_save, c_l_del = st.columns(2)
                    with c_l_save:
                        if st.form_submit_button("💾 Save Name"):
                            if edited_l_name.strip():
                                update_location_name(selected_location_to_edit, edited_l_name)
                                st.success(f"Updated location name to {edited_l_name.upper()}")
                                st.rerun()
                    with c_l_del:
                        if st.form_submit_button("🗑️ Delete Location"):
                            delete_location(selected_location_to_edit)
                            st.success(f"Deleted location {selected_location_to_edit}")
                            st.rerun()