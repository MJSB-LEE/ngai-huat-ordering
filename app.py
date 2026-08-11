import base64
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import io
import json
import os
import re
import smtplib
import urllib.parse
from PIL import Image
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
from supabase import Client, create_client

try:
    from streamlit_sortables import sort_items
except ImportError:
    st.error(
        "Please install streamlit-sortables via: pip install streamlit-sortables"
    )

st.set_page_config(
    page_title="Grocery POS & Ordering System",
    page_icon="🏪",
    layout="wide",
    initial_sidebar_state="expanded",
)

ALLOWED_IMAGE_EXTS = [
    "avif",
    "webp",
    "jpg",
    "jpeg",
    "png",
    "gif",
    "bmp",
    "tiff",
    "ico",
]

MOBILE_CSS = """
<style>
    footer {visibility: hidden;}
    
    .block-container {
        padding-top: 1rem !important;
        padding-bottom: 6rem !important;
        padding-left: 0.5rem !important;
        padding-right: 0.5rem !important;
        max-width: 100% !important;
    }

    div[data-testid="stVerticalBlockBorderWrapper"] {
        border-radius: 12px !important;
        box-shadow: 0 2px 6px rgba(0,0,0,0.15) !important;
        margin-bottom: 8px !important;
    }

    .stButton button {
        border-radius: 8px !important;
        min-height: 38px !important;
        font-weight: bold !important;
        padding: 0px 4px !important;
    }
    
    .shop-header {
        background-color: #1e1e1e;
        border-radius: 12px;
        padding: 12px;
        text-align: center;
        margin-bottom: 12px;
        border: 1px solid #333;
    }
    .shop-title {
        color: #f1c40f;
        font-size: 18px;
        font-weight: bold;
        margin: 0;
    }
    .shop-location {
        color: #bdc3c7;
        font-size: 13px;
        margin-top: 4px;
    }

    /* Horizontal layout for + / quantity / - buttons */
    div[data-testid="stHorizontalBlock"] {
        display: flex !important;
        flex-direction: row !important;
        flex-wrap: nowrap !important;
        align-items: center !important;
        justify-content: space-between !important;
        width: 100% !important;
    }

    div[data-testid="stHorizontalBlock"] > div,
    div[data-testid="stHorizontalBlock"] > div[data-testid="column"] {
        display: flex !important;
        flex-direction: row !important;
        width: 33.33% !important;
        min-width: 0 !important;
        flex: 1 1 0% !important;
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


# ==========================================
# SUPABASE INITIALIZATION & HELPER FUNCTIONS
# ==========================================
@st.cache_resource
def init_supabase() -> Client:
    return create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])


supabase = init_supabase()


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


# --- SETTINGS MANAGEMENT ---
def get_setting(key, default_value=""):
    try:
        response = (
            supabase.table("settings").select("value").eq("key", key).execute()
        )
        if response.data:
            return response.data[0]["value"]
    except Exception:
        pass
    return default_value


def save_setting(key, value):
    supabase.table("settings").upsert(
        {"key": key, "value": str(value).strip()}
    ).execute()


# --- CASHIER & USER MANAGEMENT ---
def authenticate_user(username, password):
    username_clean = username.upper().strip()

    if username.lower().strip() == "admin" and password.strip() == "1234":
        return {"name": "ADMIN", "role": "admin"}

    try:
        response = (
            supabase.table("cashiers")
            .select("*")
            .eq("name", username_clean)
            .execute()
        )
        if response.data:
            row = response.data[0]
            stored_pass = str(row.get("password") or "")
            if stored_pass == password.strip():
                return {
                    "name": row["name"],
                    "role": str(row.get("role") or "cashier").lower(),
                }
    except Exception:
        pass
    return None


@st.cache_data(ttl=10)
def get_cashiers():
    try:
        response = (
            supabase.table("cashiers")
            .select("name")
            .order("sort_order", desc=False)
            .order("name", desc=False)
            .execute()
        )
        rows = [r["name"] for r in response.data] if response.data else []
        return rows if rows else ["DEFAULT CASHIER"]
    except Exception:
        return ["DEFAULT CASHIER"]


def get_cashier_details(name):
    try:
        response = (
            supabase.table("cashiers")
            .select("*")
            .eq("name", name)
            .execute()
        )
        if response.data:
            row = response.data[0]
            return (
                row.get("password", ""),
                row.get("role", "cashier"),
                row.get("email", ""),
                row.get("smtp_password", ""),
            )
    except Exception:
        pass
    return "", "cashier", "", ""


def save_cashiers_order(ordered_names):
    for index, name in enumerate(ordered_names):
        supabase.table("cashiers").update({"sort_order": index + 1}).eq(
            "name", name
        ).execute()
    st.cache_data.clear()


def add_cashier(
    name, password="", role="cashier", email="", smtp_password=""
):
    try:
        response = (
            supabase.table("cashiers")
            .select("sort_order")
            .order("sort_order", desc=True)
            .limit(1)
            .execute()
        )
        max_order = response.data[0]["sort_order"] if response.data else 0
    except Exception:
        max_order = 0

    supabase.table("cashiers").upsert({
        "name": name.upper().strip(),
        "password": password.strip(),
        "role": role.lower().strip(),
        "sort_order": max_order + 1,
        "email": email.strip(),
        "smtp_password": smtp_password.strip(),
    }).execute()
    st.cache_data.clear()


def update_cashier_details(
    old_name, new_name, password, role, email, smtp_password
):
    try:
        response = (
            supabase.table("cashiers")
            .select("sort_order")
            .eq("name", old_name)
            .execute()
        )
        old_order = response.data[0]["sort_order"] if response.data else 1
    except Exception:
        old_order = 1

    if old_name != new_name.upper().strip():
        supabase.table("cashiers").delete().eq("name", old_name).execute()

    supabase.table("cashiers").upsert({
        "name": new_name.upper().strip(),
        "password": password.strip(),
        "role": role.lower().strip(),
        "sort_order": old_order,
        "email": email.strip(),
        "smtp_password": smtp_password.strip(),
    }).execute()
    st.cache_data.clear()


def delete_cashier(name):
    supabase.table("cashiers").delete().eq("name", name).execute()
    st.cache_data.clear()


# --- LOCATION MANAGEMENT ---
@st.cache_data(ttl=10)
def get_locations():
    try:
        response = (
            supabase.table("locations")
            .select("name")
            .order("sort_order", desc=False)
            .order("name", desc=False)
            .execute()
        )
        rows = [r["name"] for r in response.data] if response.data else []
        return rows if rows else ["MAIN BRANCH"]
    except Exception:
        return ["MAIN BRANCH"]


def save_locations_order(ordered_names):
    for index, name in enumerate(ordered_names):
        supabase.table("locations").update({"sort_order": index + 1}).eq(
            "name", name
        ).execute()
    st.cache_data.clear()


def add_location(name):
    try:
        response = (
            supabase.table("locations")
            .select("sort_order")
            .order("sort_order", desc=True)
            .limit(1)
            .execute()
        )
        max_order = response.data[0]["sort_order"] if response.data else 0
    except Exception:
        max_order = 0

    supabase.table("locations").upsert(
        {"name": name.upper().strip(), "sort_order": max_order + 1}
    ).execute()
    st.cache_data.clear()


def update_location_name(old_name, new_name):
    try:
        response = (
            supabase.table("locations")
            .select("sort_order")
            .eq("name", old_name)
            .execute()
        )
        old_order = response.data[0]["sort_order"] if response.data else 1
    except Exception:
        old_order = 1

    supabase.table("locations").delete().eq("name", old_name).execute()
    supabase.table("locations").upsert(
        {"name": new_name.upper().strip(), "sort_order": old_order}
    ).execute()
    st.cache_data.clear()


def delete_location(name):
    supabase.table("locations").delete().eq("name", name).execute()
    st.cache_data.clear()


# --- ORDER NUMBERS & SAVING ---
def get_next_order_number():
    current_yymm = datetime.now().strftime("%y%m")
    try:
        response = (
            supabase.table("order_counter")
            .select("last_seq")
            .eq("yymm", current_yymm)
            .execute()
        )
        if response.data:
            next_seq = response.data[0]["last_seq"] + 1
        else:
            next_seq = 1
    except Exception:
        next_seq = 1

    order_num = f"{current_yymm}-{next_seq:04d}"
    return order_num, current_yymm, next_seq


def save_new_order(
    order_no,
    customer,
    location,
    cashier,
    items_summary,
    total_amount,
    yymm,
    seq,
):
    created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    supabase.table("orders").upsert({
        "order_no": order_no,
        "customer_name": customer,
        "location": location,
        "cashier": cashier,
        "items_summary": items_summary,
        "total_amount": total_amount,
        "status": "Pending",
        "created_at": created_at,
        "completed_at": "",
        "cancelled_at": "",
        "cancel_reason": "",
    }).execute()

    supabase.table("order_counter").upsert(
        {"yymm": yymm, "last_seq": seq}
    ).execute()
    st.cache_data.clear()


def get_orders_by_status(status, month_filter=None):
    query = (
        supabase.table("orders")
        .select(
            "order_no, customer_name, location, cashier, items_summary, total_amount, created_at, completed_at, cancelled_at, cancel_reason"
        )
        .eq("status", status)
    )

    if month_filter and month_filter != "All Months":
        query = query.gte("created_at", f"{month_filter}-01").lte(
            "created_at", f"{month_filter}-31 23:59:59"
        )

    response = query.order("created_at", desc=True).execute()

    rows = []
    for o in response.data:
        rows.append((
            o.get("order_no"),
            o.get("customer_name"),
            o.get("location"),
            o.get("cashier"),
            o.get("items_summary"),
            float(o.get("total_amount") or 0.0),
            o.get("created_at"),
            o.get("completed_at"),
            o.get("cancelled_at"),
            o.get("cancel_reason"),
        ))
    return rows


def get_available_order_months():
    try:
        response = supabase.table("orders").select("created_at").execute()
        months = sorted(
            list(
                set(
                    o["created_at"][:7]
                    for o in response.data
                    if o.get("created_at") and len(o["created_at"]) >= 7
                )
            ),
            reverse=True,
        )
    except Exception:
        months = []

    current_m = datetime.now().strftime("%Y-%m")
    if current_m not in months:
        months.insert(0, current_m)
    return ["All Months"] + months


# --- MENU / INVENTORY MANAGEMENT ---
@st.cache_data(ttl=10)
def get_menu_items():
    response = supabase.table("menu").select("*").execute()
    menu = {}
    for row in response.data:
        menu[row["code"]] = {
            "name": row["name"],
            "category": row["category"],
            "price": float(row["price"]),
            "image": row.get("image_data"),
        }
    return menu


def add_or_update_menu_item(code, name, category, price, image_data):
    if image_data is None:
        response = (
            supabase.table("menu")
            .select("image_data")
            .eq("code", code)
            .execute()
        )
        if response.data:
            image_data = response.data[0].get("image_data")

    supabase.table("menu").upsert({
        "code": code,
        "name": name,
        "category": category,
        "price": price,
        "image_data": image_data,
    }).execute()
    st.cache_data.clear()


def delete_menu_item(code):
    supabase.table("menu").delete().eq("code", code).execute()
    st.cache_data.clear()


def update_order_status(order_no, status, cancel_reason=""):
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if status == "Completed":
        supabase.table("orders").update(
            {"status": status, "completed_at": now_str}
        ).eq("order_no", order_no).execute()
    elif status == "Cancelled":
        supabase.table("orders").update({
            "status": status,
            "cancelled_at": now_str,
            "cancel_reason": cancel_reason,
        }).eq("order_no", order_no).execute()
    st.cache_data.clear()


# ==========================================
# SHOPEE-STYLE TROLLEY DIALOG (MODAL OVERLAY)
# ==========================================
@st.dialog("🛒 Your Shopping Trolley")
def show_trolley_modal(menu_data, display_location):
    if not isinstance(st.session_state.cart, dict) or not st.session_state.cart:
        st.info("Your trolley is empty. Select items from the catalog.")
        return

    total_amount = 0.0
    items_summary_list = []

    st.markdown("##### 📝 Review Selected Items")
    for code, qty in list(st.session_state.cart.items()):
        if code in menu_data:
            item = menu_data[code]
            subtotal = item["price"] * qty
            total_amount += subtotal
            items_summary_list.append(f"[{code}] {item['name']} x{qty}")

            with st.container(border=True):
                c_info, c_qty = st.columns([2.2, 1])
                with c_info:
                    st.write(f"**{item['name']}**")
                    st.caption(f"RM {item['price']:.2f} × {qty} = **RM {subtotal:.2f}**")
                with c_qty:
                    b1, b2 = st.columns(2)
                    with b1:
                        if st.button("➖", key=f"dialog_m_{code}", use_container_width=True):
                            st.session_state.cart[code] -= 1
                            if st.session_state.cart[code] <= 0:
                                del st.session_state.cart[code]
                            st.rerun()
                    with b2:
                        if st.button("➕", key=f"dialog_p_{code}", use_container_width=True):
                            st.session_state.cart[code] += 1
                            st.rerun()

    st.write("---")
    st.markdown(f"### **Total Amount: RM {total_amount:.2f}**")

    client_name = st.text_input("Customer Name *", placeholder="e.g. Mr. Tan")
    customer_comment = st.text_area(
        "Remarks / Notes (Optional)", placeholder="e.g. Packing requests..."
    )

    col_sub, col_clr = st.columns([3, 1])
    with col_sub:
        if st.button(
            "🚀 Confirm & Submit Order",
            type="primary",
            use_container_width=True,
        ):
            if not client_name.strip():
                st.error("⚠️ Please fill in Customer Name!")
            else:
                items_summary_str = ", ".join(items_summary_list)
                current_order_no, current_yymm, current_seq = (
                    get_next_order_number()
                )

                save_new_order(
                    current_order_no,
                    client_name.strip(),
                    display_location,
                    "CLIENT MOBILE",
                    items_summary_str,
                    total_amount,
                    current_yymm,
                    current_seq,
                )

                st.session_state.cart = {}
                st.balloons()
                st.success(
                    f"🎉 Order `{current_order_no}` placed successfully!"
                )
                st.rerun()
    with col_clr:
        if st.button("🗑️ Clear", use_container_width=True):
            st.session_state.cart = {}
            st.rerun()


# ==========================================
# APP SESSION STATE & AUTHENTICATION ROUTING
# ==========================================
if "cart" not in st.session_state or not isinstance(st.session_state.cart, dict):
    st.session_state.cart = {}
if "editing_code" not in st.session_state:
    st.session_state.editing_code = None

if "authenticated_user" not in st.session_state:
    st.session_state.authenticated_user = None
if "user_role" not in st.session_state:
    st.session_state.user_role = "client"

query_params = st.query_params

# Admin override parameter check
if query_params.get("admin", "false").lower() == "true":
    st.session_state.authenticated_user = "ADMIN"
    st.session_state.user_role = "admin"

# Hide sidebar staff login when customer uses a direct shop branch link
is_customer_link = bool(query_params.get("shop"))

if not is_customer_link:
    st.sidebar.markdown("### 🔑 Staff Portal Login")

    if st.session_state.authenticated_user is None:
        with st.sidebar.form("sidebar_login_form"):
            login_user = st.text_input("Username / Cashier Name", placeholder="e.g. admin or CASHIER1")
            login_pass = st.text_input("Password", type="password", placeholder="••••••••")
            submit_login = st.form_submit_button("🔓 Log In", use_container_width=True)

            if submit_login:
                user_info = authenticate_user(login_user, login_pass)
                if user_info:
                    st.session_state.authenticated_user = user_info["name"]
                    st.session_state.user_role = user_info["role"]
                    st.success(f"Welcome, {user_info['name']}!")
                    st.rerun()
                else:
                    st.error("Invalid Username or Password!")
    else:
        st.sidebar.success(
            f"👤 **{st.session_state.authenticated_user}**\n\nRole: `{st.session_state.user_role.upper()}`"
        )
        if st.sidebar.button("🔒 Log Out", use_container_width=True):
            st.session_state.authenticated_user = None
            st.session_state.user_role = "client"
            st.query_params.clear()
            st.rerun()

# Load Global Settings
company_name_setting = get_setting("company_name", "SYARIKAT NGAI HUAT SDN BHD")
active_branch_setting = get_setting("active_branch_location", "")
img_size = int(get_setting("item_image_width", "100"))

# ==========================================
# 1. CLIENT HP SELF-ORDERING PORTAL (PUBLIC)
# ==========================================
if st.session_state.user_role == "client":
    st.markdown(MOBILE_CSS, unsafe_allow_html=True)
    components.html(LIVE_SEARCH_JS, height=0)

    menu_data = get_menu_items()
    active_locations = get_locations()

    # Dynamic URL Shop parameter detection (e.g. ?shop=TUNGKU)
    url_shop = query_params.get("shop", "").strip().upper()
    if url_shop and url_shop in [loc.upper() for loc in active_locations]:
        display_location = next(
            loc for loc in active_locations if loc.upper() == url_shop
        )
    else:
        display_location = (
            active_branch_setting
            if active_branch_setting in active_locations
            else (active_locations[0] if active_locations else "MAIN BRANCH")
        )

    st.markdown(
        f"""
        <div class="shop-header">
            <div class="shop-title">{company_name_setting}</div>
            <div class="shop-location">📍 Branch Location: <strong>{display_location}</strong></div>
        </div>
    """,
        unsafe_allow_html=True,
    )

    st.markdown("##### 🔎 Search & Filter Items")
    search_query = st.text_input(
        "Search Item Name or Code",
        key="live_search_key",
        placeholder="Type item name or code...",
        label_visibility="collapsed",
    )

    categories = ["All"] + sorted(
        list(set(item["category"] for item in menu_data.values()))
    )
    selected_category = st.radio("Category:", categories, horizontal=True)

    filtered_menu = {}
    for code, details in menu_data.items():
        matches_cat = (
            selected_category == "All"
            or details["category"] == selected_category
        )
        matches_search = (
            not search_query.strip()
            or search_query.lower() in details["name"].lower()
            or search_query.lower() in code.lower()
        )
        if matches_cat and matches_search:
            filtered_menu[code] = details

    st.markdown("##### 📦 Item Catalog")
    if not filtered_menu:
        st.warning("No items match your search or selected category.")
    else:
        # BATCHING FORM: Adjust quantities freely without page reloads
        with st.form("catalog_batch_form"):
            temp_quantities = {}
            for code, item in filtered_menu.items():
                with st.container(border=True):
                    if item.get("image"):
                        col_img, col_detail, col_qty = st.columns([1, 1.8, 1])
                        with col_img:
                            st.image(item["image"], use_container_width=True)
                        with col_detail:
                            st.markdown(f"**[{code}] {item['name']}**")
                            st.markdown(
                                f"<span style='color:#27ae60;font-weight:bold;'>RM {item['price']:.2f}</span>",
                                unsafe_allow_html=True,
                            )
                        with col_qty:
                            default_val = st.session_state.cart.get(code, 0)
                            temp_quantities[code] = st.number_input(
                                "Qty",
                                min_value=0,
                                max_value=99,
                                value=default_val,
                                key=f"batch_qty_{code}",
                            )
                    else:
                        col_detail, col_qty = st.columns([2.5, 1])
                        with col_detail:
                            st.markdown(f"**[{code}] {item['name']}**")
                            st.markdown(
                                f"<span style='color:#27ae60;font-weight:bold;'>RM {item['price']:.2f}</span>",
                                unsafe_allow_html=True,
                            )
                        with col_qty:
                            default_val = st.session_state.cart.get(code, 0)
                            temp_quantities[code] = st.number_input(
                                "Qty",
                                min_value=0,
                                max_value=99,
                                value=default_val,
                                key=f"batch_qty_{code}",
                            )

            st.write("---")
            submit_to_trolley = st.form_submit_button(
                "🛒 Sync to Trolley & Review Order",
                type="primary",
                use_container_width=True,
            )

        if submit_to_trolley:
            for code, qty in temp_quantities.items():
                if qty > 0:
                    st.session_state.cart[code] = qty
                elif code in st.session_state.cart:
                    del st.session_state.cart[code]

            show_trolley_modal(menu_data, display_location)

    # FLOATING QUICK SUMMARY BAR FOR ALREADY SYNCED CART
    total_qty = sum(st.session_state.cart.values()) if isinstance(st.session_state.cart, dict) else 0
    total_amt = sum(
        menu_data[code]["price"] * qty 
        for code, qty in st.session_state.cart.items() 
        if code in menu_data
    ) if isinstance(st.session_state.cart, dict) else 0.0

    if total_qty > 0:
        st.write("---")
        with st.container(border=True):
            col_bar_info, col_bar_btn = st.columns([2, 1])
            with col_bar_info:
                st.markdown(f"### 🛒 **{total_qty} Items** | **RM {total_amt:.2f}**")
            with col_bar_btn:
                if st.button("Open Trolley 🛍️", type="primary", use_container_width=True):
                    show_trolley_modal(menu_data, display_location)

# ==========================================
# 2. CASHIER VIEW (LOCKED TO POS & ORDERS)
# ==========================================
elif st.session_state.user_role == "cashier":
    st.title(
        f"🏪 {company_name_setting} - Cashier Counter ({st.session_state.authenticated_user})"
    )

    tab_pos, tab_process = st.tabs(["🛒 Sales Counter", "⏳ Processing Orders"])

    with tab_pos:
        st.subheader("Sales Counter (Cashier Mode)")
        st.info("Staff POS interface for counter cashiers.")

    with tab_process:
        c_head, c_month_select = st.columns([3, 1.2])
        with c_head:
            st.subheader("📊 Processing Orders Management")
        with c_month_select:
            month_options = get_available_order_months()
            selected_month = st.selectbox(
                "📅 Filter by Month:", month_options, index=0, key="cashier_m_filter"
            )

        pending_orders = get_orders_by_status("Pending", selected_month)
        subtotal_pending = sum(o[5] for o in pending_orders)

        st.metric(
            "Pending Orders Value",
            f"RM {subtotal_pending:.2f}",
            f"{len(pending_orders)} pending",
        )
        st.write("---")

        if not pending_orders:
            st.info(f"No pending orders for {selected_month}.")
        else:
            for order in pending_orders:
                (
                    order_no,
                    cust_name,
                    loc,
                    cashier,
                    items_str,
                    total_amt,
                    created_at,
                    _,
                    _,
                    _,
                ) = order

                with st.container(border=True):
                    col1, col2, col3 = st.columns([2.5, 3, 1.8])
                    with col1:
                        st.markdown(f"🏷️ **Order No:** `{order_no}`")
                        st.write(f"👤 **Customer:** {cust_name}")
                        st.caption(
                            f"📍 Location: {loc} | Cashier: {cashier}"
                        )
                        st.caption(f"🕒 **Created Time:** {created_at}")
                    with col2:
                        st.write("🛒 **Summary:**")
                        st.write(items_str)
                        st.markdown(
                            f"💰 **Total Amount:** **RM {total_amt:.2f}**"
                        )

                    with col3:
                        st.write(" ")
                        if st.button(
                            "✅ Complete Order",
                            key=f"cashier_comp_{order_no}",
                            use_container_width=True,
                            type="primary",
                        ):
                            update_order_status(order_no, "Completed")
                            st.success(f"Order {order_no} completed!")
                            st.rerun()

                        if st.button(
                            "❌ Cancel Order",
                            key=f"cashier_canc_{order_no}",
                            use_container_width=True,
                        ):
                            update_order_status(
                                order_no, "Cancelled", "Cancelled by Cashier"
                            )
                            st.success(f"Order {order_no} cancelled!")
                            st.rerun()

# ==========================================
# 3. FULL ADMIN MANAGEMENT VIEW
# ==========================================
elif st.session_state.user_role == "admin":
    st.title(f"🏪 {company_name_setting} - Staff POS & Admin")

    tab_pos, tab_process, tab_item_out, tab_manage, tab_settings = st.tabs([
        "🛒 Sales Counter",
        "⏳ Processing Orders",
        "📊 Monthly Item Out Report",
        "📦 Add / Manage Items",
        "⚙️ System Settings",
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
            selected_month = st.selectbox(
                "📅 Filter by Month:", month_options, index=0
            )

        pending_orders = get_orders_by_status("Pending", selected_month)
        completed_orders = get_orders_by_status("Completed", selected_month)
        cancelled_orders = get_orders_by_status("Cancelled", selected_month)

        subtotal_pending = sum(o[5] for o in pending_orders)
        subtotal_completed = sum(o[5] for o in completed_orders)
        subtotal_cancelled = sum(o[5] for o in cancelled_orders)

        m1, m2, m3 = st.columns(3)
        with m1:
            st.metric(
                "Pending Orders Value",
                f"RM {subtotal_pending:.2f}",
                f"{len(pending_orders)} pending",
            )
        with m2:
            st.metric(
                "Total Completed Revenue",
                f"RM {subtotal_completed:.2f}",
                f"{len(completed_orders)} completed",
            )
        with m3:
            st.metric(
                "Total Cancelled Amount",
                f"RM {subtotal_cancelled:.2f}",
                f"{len(cancelled_orders)} cancelled",
            )

        st.write("---")

        proc_tab1, proc_tab2 = st.tabs([
            f"⏳ Active Pending Orders ({len(pending_orders)})",
            "📜 Order History",
        ])

        with proc_tab1:
            if not pending_orders:
                st.info(f"No pending orders for {selected_month}.")
            else:
                for order in pending_orders:
                    (
                        order_no,
                        cust_name,
                        loc,
                        cashier,
                        items_str,
                        total_amt,
                        created_at,
                        _,
                        _,
                        _,
                    ) = order

                    with st.container(border=True):
                        col1, col2, col3 = st.columns([2.5, 3, 1.8])
                        with col1:
                            st.markdown(f"🏷️ **Order No:** `{order_no}`")
                            st.write(f"👤 **Customer:** {cust_name}")
                            st.caption(
                                f"📍 Location: {loc} | Cashier: {cashier}"
                            )
                            st.caption(f"🕒 **Created Time:** {created_at}")
                        with col2:
                            st.write("🛒 **Summary:**")
                            st.write(items_str)
                            st.markdown(
                                f"💰 **Total Amount:** **RM {total_amt:.2f}**"
                            )

                        with col3:
                            st.write(" ")
                            if st.button(
                                "✅ Complete Order",
                                key=f"complete_{order_no}",
                                use_container_width=True,
                                type="primary",
                            ):
                                update_order_status(order_no, "Completed")
                                st.success(f"Order {order_no} completed!")
                                st.rerun()

                            if st.button(
                                "❌ Cancel Order",
                                key=f"cancel_btn_{order_no}",
                                use_container_width=True,
                            ):
                                update_order_status(
                                    order_no, "Cancelled", "Cancelled by Staff"
                                )
                                st.success(f"Order {order_no} cancelled!")
                                st.rerun()

        with proc_tab2:
            hist_tab1, hist_tab2 = st.tabs(
                ["✅ Completed Orders", "❌ Cancelled Orders"]
            )

            with hist_tab1:
                if not completed_orders:
                    st.caption(f"No completed orders for {selected_month}.")
                else:
                    comp_data = [
                        [o[0], o[1], o[2], o[3], o[4], o[5], o[6], o[7]]
                        for o in completed_orders
                    ]
                    completed_df = pd.DataFrame(
                        comp_data,
                        columns=[
                            "Order No",
                            "Customer",
                            "Location",
                            "Cashier",
                            "Items Summary",
                            "Total (RM)",
                            "Created Time",
                            "Completed Time",
                        ],
                    )
                    st.dataframe(completed_df, use_container_width=True)

            with hist_tab2:
                if not cancelled_orders:
                    st.caption(f"No cancelled orders for {selected_month}.")
                else:
                    canc_data = [
                        [o[0], o[1], o[2], o[3], o[4], o[5], o[9], o[6], o[8]]
                        for o in cancelled_orders
                    ]
                    cancelled_df = pd.DataFrame(
                        canc_data,
                        columns=[
                            "Order No",
                            "Customer",
                            "Location",
                            "Cashier",
                            "Items Summary",
                            "Total (RM)",
                            "Cancellation Reason",
                            "Created Time",
                            "Cancelled Time",
                        ],
                    )
                    st.dataframe(cancelled_df, use_container_width=True)

    with tab_item_out:
        st.subheader(
            "📊 Monthly Item Out Quantity Summary (AutoCount Cash Sales)"
        )
        cs_file = st.file_uploader(
            "Upload AutoCount Cash Sales File",
            type=["xlsx", "csv"],
            key="cs_report_uploader",
        )
        if cs_file:
            try:
                df_cs = (
                    pd.read_csv(cs_file)
                    if cs_file.name.endswith(".csv")
                    else pd.read_excel(cs_file)
                )
                st.dataframe(df_cs.head(5), use_container_width=True)
                cols = df_cs.columns.tolist()
                c1, c2, c3, c4 = st.columns(4)
                with c1:
                    col_item_code = st.selectbox(
                        "Item Code Column:", cols, index=0
                    )
                with c2:
                    col_item_desc = st.selectbox(
                        "Description Column:",
                        cols,
                        index=1 if len(cols) > 1 else 0,
                    )
                with c3:
                    col_qty = st.selectbox(
                        "Quantity Column:",
                        cols,
                        index=2 if len(cols) > 2 else 0,
                    )
                with c4:
                    col_date = st.selectbox(
                        "Date Column (Optional):",
                        ["(No Date Column)"] + cols,
                        index=0,
                    )

                df_cs[col_qty] = pd.to_numeric(
                    df_cs[col_qty], errors="coerce"
                ).fillna(0)
                summary_df = df_cs.groupby(
                    [col_item_code, col_item_desc], as_index=False
                )[col_qty].sum()
                summary_df.columns = [
                    "Item Code",
                    "Description",
                    "Total Out Quantity",
                ]
                st.dataframe(
                    summary_df.sort_values(
                        by="Total Out Quantity", ascending=False
                    ),
                    use_container_width=True,
                )
            except Exception as e:
                st.error(f"Error reading file: {e}")

    # --- TAB 4: ADD / EDIT / MANAGE INVENTORY ---
    with tab_manage:
        current_menu = get_menu_items()

        actions = [
            "➕ Add New Item",
            "✏️ Edit / Update Item",
            "📥 Import from AutoCount",
        ]

        if "manage_action" not in st.session_state:
            st.session_state.manage_action = "➕ Add New Item"

        default_index = (
            actions.index(st.session_state.manage_action)
            if st.session_state.manage_action in actions
            else 0
        )

        col_forms, col_list = st.columns([2, 3])

        with col_forms:
            mode = st.radio(
                "Action:",
                actions,
                index=default_index,
                horizontal=True,
            )
            st.session_state.manage_action = mode

            if mode == "➕ Add New Item":
                st.subheader("➕ Add New Item")
                with st.form("add_item_form", clear_on_submit=True):
                    new_code = st.text_input("Item Code (SKU)").upper().strip()
                    new_name = st.text_input("Item Name")
                    new_cat = st.text_input("Category").capitalize().strip()
                    new_price = st.number_input(
                        "Price (RM)", min_value=0.0, step=0.10, value=3.00
                    )
                    uploaded_file = st.file_uploader(
                        "Upload Image", type=ALLOWED_IMAGE_EXTS
                    )

                    if st.form_submit_button("Save New Item"):
                        if new_code and new_name and new_cat:
                            add_or_update_menu_item(
                                new_code,
                                new_name,
                                new_cat,
                                new_price,
                                image_to_base64(uploaded_file),
                            )
                            st.success(f"Saved [{new_code}] {new_name}")
                            st.rerun()

            elif mode == "✏️ Edit / Update Item":
                st.subheader("✏️ Edit Item")
                if not current_menu:
                    st.info("No items in inventory to edit.")
                else:
                    item_options = {
                        f"[{code}] {details['name']}": code
                        for code, details in current_menu.items()
                    }
                    item_keys = list(item_options.keys())

                    selected_idx = 0
                    if st.session_state.editing_code:
                        for i, (k, v) in enumerate(item_options.items()):
                            if v == st.session_state.editing_code:
                                selected_idx = i
                                break

                    selected_label = st.selectbox(
                        "Select Item to Edit:", item_keys, index=selected_idx
                    )
                    selected_code = item_options[selected_label]
                    selected_item = current_menu[selected_code]

                    with st.form("edit_item_form"):
                        edit_code = st.text_input(
                            "Item Code (SKU)", value=selected_code
                        ).upper().strip()
                        edit_name = st.text_input(
                            "Item Name", value=selected_item["name"]
                        )
                        edit_cat = st.text_input(
                            "Category", value=selected_item["category"]
                        )
                        edit_price = st.number_input(
                            "Price (RM)", value=float(selected_item["price"])
                        )
                        edit_uploaded_file = st.file_uploader(
                            "Upload New Image (Optional)",
                            type=ALLOWED_IMAGE_EXTS,
                        )

                        if st.form_submit_button("💾 Save Changes"):
                            img_data = (
                                image_to_base64(edit_uploaded_file)
                                if edit_uploaded_file
                                else None
                            )

                            if edit_code != selected_code:
                                delete_menu_item(selected_code)

                            add_or_update_menu_item(
                                edit_code,
                                edit_name,
                                edit_cat,
                                edit_price,
                                img_data,
                            )
                            st.session_state.editing_code = edit_code
                            st.success(f"Updated item [{edit_code}] successfully!")
                            st.rerun()

                    st.write("---")
                    if st.button(
                        f"🗑️ Delete Item [{selected_code}]",
                        use_container_width=True,
                    ):
                        delete_menu_item(selected_code)
                        st.session_state.editing_code = None
                        st.success(f"Deleted item [{selected_code}]!")
                        st.rerun()

            else:
                st.subheader("📥 Import Inventory from AutoCount")
                st.caption(
                    "Upload AutoCount Excel or CSV file to bulk import/update items."
                )

                autocount_file = st.file_uploader(
                    "Upload File",
                    type=["xlsx", "csv"],
                    key="autocount_import_uploader",
                )

                if autocount_file:
                    try:
                        df_ac = (
                            pd.read_csv(autocount_file)
                            if autocount_file.name.endswith(".csv")
                            else pd.read_excel(autocount_file)
                        )

                        st.markdown("**Preview Uploaded File:**")
                        st.dataframe(df_ac.head(5), use_container_width=True)

                        cols = df_ac.columns.tolist()
                        cat_options = ["(Set Fixed Category)"] + cols

                        c1, c2, c3, c4 = st.columns(4)

                        with c1:
                            col_code = st.selectbox(
                                "Item Code Column:", cols, index=0
                            )
                        with c2:
                            col_name = st.selectbox(
                                "Item Name Column:",
                                cols,
                                index=1 if len(cols) > 1 else 0,
                            )
                        with c3:
                            default_cat_idx = 3 if len(cols) > 2 else 0
                            col_cat = st.selectbox(
                                "Category Column:",
                                cat_options,
                                index=default_cat_idx,
                            )
                        with c4:
                            col_price = st.selectbox(
                                "Price Column:",
                                cols,
                                index=3 if len(cols) > 3 else 0,
                            )

                        fixed_cat_val = ""
                        if col_cat == "(Set Fixed Category)":
                            fixed_cat_val = st.text_input(
                                "Type Category Name for All Imported Items:",
                                value="General",
                            )

                        if st.button(
                            "🚀 Start Import to Supabase", type="primary"
                        ):
                            imported_count = 0
                            for _, row in df_ac.iterrows():
                                code_val = (
                                    str(row[col_code]).upper().strip()
                                    if pd.notna(row[col_code])
                                    else ""
                                )
                                name_val = (
                                    str(row[col_name]).strip()
                                    if pd.notna(row[col_name])
                                    else ""
                                )

                                if col_cat == "(Set Fixed Category)":
                                    cat_val = (
                                        fixed_cat_val.capitalize().strip()
                                        if fixed_cat_val.strip()
                                        else "General"
                                    )
                                else:
                                    cat_val = (
                                        str(row[col_cat]).capitalize().strip()
                                        if pd.notna(row[col_cat])
                                        else "General"
                                    )

                                raw_price = (
                                    str(row[col_price])
                                    if pd.notna(row[col_price])
                                    else "0.0"
                                )
                                cleaned_price_str = re.sub(
                                    r"[^\d.]", "", raw_price
                                )
                                try:
                                    price_val = (
                                        float(cleaned_price_str)
                                        if cleaned_price_str
                                        else 0.0
                                    )
                                except (ValueError, TypeError):
                                    price_val = 0.0

                                if code_val and name_val:
                                    add_or_update_menu_item(
                                        code_val,
                                        name_val,
                                        cat_val,
                                        price_val,
                                        None,
                                    )
                                    imported_count += 1

                            st.success(
                                f"🎉 Successfully imported {imported_count} items into Supabase!"
                            )
                            st.rerun()

                    except Exception as e:
                        st.error(f"Error reading AutoCount file: {e}")

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
                        st.caption(
                            f"RM {details['price']:.2f} | Category:"
                            f" {details['category']}"
                        )
                    with c_edit:
                        if st.button(
                            "✏️ Edit",
                            key=f"manage_{code}",
                            use_container_width=True,
                        ):
                            st.session_state.editing_code = code
                            st.session_state.manage_action = "✏️ Edit / Update Item"
                            st.rerun()

    # --- TAB 5: SYSTEM CONFIGURATION, USER & LOCATION MANAGEMENT ---
    with tab_settings:
        st.subheader("⚙️ System Configuration & General Settings")

        with st.container(border=True):
            st.markdown("### 🏢 Company & Active Branch Settings")

            new_comp_name = st.text_input(
                "Company Name", value=company_name_setting
            )

            all_locs = get_locations()
            current_loc_idx = (
                all_locs.index(active_branch_setting)
                if active_branch_setting in all_locs
                else 0
            )
            new_active_loc = st.selectbox(
                "Active Client Portal Branch Location",
                all_locs,
                index=current_loc_idx,
            )

            if st.button("💾 Save Company & Branch Settings"):
                save_setting("company_name", new_comp_name.strip())
                save_setting("active_branch_location", new_active_loc)
                st.success(
                    "Company Name and Active Branch updated successfully!"
                )
                st.rerun()

        st.write("---")

        with st.container(border=True):
            st.markdown("### 🖼️ Catalog Image Display Size")
            new_size = st.slider(
                "Product Image Width (pixels)", 50, 300, img_size, 10
            )
            if st.button("💾 Save Image Size"):
                save_setting("item_image_width", str(new_size))
                st.success("Saved image display size!")
                st.rerun()

        st.write("---")

        with st.container(border=True):
            st.markdown("### 🔗 Shareable Branch Links")
            st.caption(
                "Copy and send these exact links to customers or turn them into QR codes:"
            )

            base_app_url = "https://t-ordering.streamlit.app"
            for loc in get_locations():
                encoded_loc = urllib.parse.quote(loc)
                branch_link = f"{base_app_url}/?shop={encoded_loc}"
                st.code(branch_link, language="text")

        st.write("---")

        col_users, col_locs = st.columns(2)

        # Cashiers & Users Role Management
        with col_users:
            with st.container(border=True):
                st.markdown("### 👤 User & Cashier Management")

                with st.form("add_cashier_form", clear_on_submit=True):
                    st.caption("Add new staff member / cashier login:")
                    new_c_name = st.text_input("Username / Cashier Name *").upper().strip()
                    new_c_pass = st.text_input("Login Password *", type="password")
                    new_c_role = st.selectbox("Role Permission", ["cashier", "admin"])
                    new_c_email = st.text_input("Gmail Address (Optional)")
                    new_c_smtp = st.text_input(
                        "Gmail App Password (Optional)", type="password"
                    )

                    if st.form_submit_button("➕ Add User"):
                        if new_c_name and new_c_pass:
                            add_cashier(
                                new_c_name,
                                new_c_pass,
                                new_c_role,
                                new_c_email,
                                new_c_smtp,
                            )
                            st.success(f"Added {new_c_role.upper()} user `{new_c_name}`")
                            st.rerun()
                        else:
                            st.error("Please fill in both Username and Password!")

                st.write("---")
                st.markdown("**Drag to Reorder Cashiers Display:**")
                current_cashiers_list = get_cashiers()
                sorted_cashiers = sort_items(
                    current_cashiers_list, key="sort_cashiers"
                )
                if st.button("💾 Save Display Order", use_container_width=True):
                    save_cashiers_order(sorted_cashiers)
                    st.rerun()

                st.write("---")
                st.markdown("**Manage Existing User:**")
                selected_cashier_to_edit = st.selectbox(
                    "Select User to Edit/Delete:",
                    current_cashiers_list,
                    key="sel_cashier_edit",
                )
                c_pass, c_role, c_email, c_smtp = get_cashier_details(
                    selected_cashier_to_edit
                )

                with st.form("form_manage_selected_cashier"):
                    edited_c_name = st.text_input(
                        "Username", value=selected_cashier_to_edit
                    )
                    edited_c_pass = st.text_input(
                        "Password", value=c_pass, type="password"
                    )
                    edited_c_role = st.selectbox(
                        "Role Permission",
                        ["cashier", "admin"],
                        index=0 if c_role == "cashier" else 1,
                    )
                    edited_c_email = st.text_input(
                        "Gmail Address", value=c_email
                    )
                    edited_c_smtp = st.text_input(
                        "Gmail App Password", value=c_smtp, type="password"
                    )

                    c_c_save, c_c_del = st.columns(2)
                    with c_c_save:
                        if st.form_submit_button("💾 Save Changes"):
                            if edited_c_name.strip() and edited_c_pass.strip():
                                update_cashier_details(
                                    selected_cashier_to_edit,
                                    edited_c_name,
                                    edited_c_pass,
                                    edited_c_role,
                                    edited_c_email,
                                    edited_c_smtp,
                                )
                                st.success(
                                    f"Updated user `{edited_c_name.upper()}`"
                                )
                                st.rerun()
                            else:
                                st.error("Username and Password cannot be empty!")
                    with c_c_del:
                        if st.form_submit_button("🗑️ Delete User"):
                            delete_cashier(selected_cashier_to_edit)
                            st.success(
                                f"Deleted user `{selected_cashier_to_edit}`"
                            )
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
                sorted_locations = sort_items(
                    current_locations_list, key="sort_locations"
                )
                if st.button("💾 Save Location Order", use_container_width=True):
                    save_locations_order(sorted_locations)
                    st.rerun()

                st.write("---")
                st.markdown("**Manage Selected Location:**")
                selected_location_to_edit = st.selectbox(
                    "Select Location to Edit/Delete:",
                    current_locations_list,
                    key="sel_loc_edit",
                )

                with st.form("form_manage_selected_location"):
                    edited_l_name = st.text_input(
                        "Location Name", value=selected_location_to_edit
                    )
                    c_l_save, c_l_del = st.columns(2)
                    with c_l_save:
                        if st.form_submit_button("💾 Save Name"):
                            if edited_l_name.strip():
                                update_location_name(
                                    selected_location_to_edit, edited_l_name
                                )
                                st.success(
                                    "Updated location name to"
                                    f" {edited_l_name.upper()}"
                                )
                                st.rerun()
                    with c_l_del:
                        if st.form_submit_button("🗑️ Delete Location"):
                            delete_location(selected_location_to_edit)
                            st.success(
                                f"Deleted location {selected_location_to_edit}"
                            )
                            st.rerun()
