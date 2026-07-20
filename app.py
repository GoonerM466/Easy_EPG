import gzip
import io
import re
import requests
import xml.etree.ElementTree as ET
import streamlit as st
from datetime import datetime, timezone, timedelta

st.set_page_config(page_title="Easy EPG", layout="wide")

# --- Security Gateway ---
def check_password():
    if "password_correct" not in st.session_state:
        st.session_state.password_correct = False

    if st.session_state.password_correct:
        return True

    st.subheader("🔒 Access Restricted")
    with st.form(key="login_form", clear_on_submit=False):
        user_input = st.text_input("Enter Passphrase Key", type="password")
        submit_button = st.form_submit_button(label="Verify Key & Access")
        if submit_button:
            if user_input == st.secrets["access_password"]:
                st.session_state.password_correct = True
                st.rerun()
            else:
                st.error("Invalid Passphrase Token.")
    return False

if not check_password():
    st.stop()

st.title("📺 Easy EPG")

# --- Custom UI Pane Constraints & Global Theme Tints ---
st.markdown("""
<style>
    [data-testid="stHorizontalBlock"] {
        height: 78vh;
        overflow: hidden;
    }
    [data-testid="stHorizontalBlock"] > div:nth-child(1) {
        max-height: 78vh;
        overflow-y: auto !important;
        padding-right: 15px;
    }
    [data-testid="stHorizontalBlock"] > div:nth-child(2) {
        max-height: 78vh;
        overflow-y: auto !important;
        padding-left: 20px;
        border-left: 1px solid rgba(49, 51, 63, 0.2);
    }
    .dir-ch-title {
        font-size: 1.1rem !important;
        font-weight: 600 !important;
        margin: 0 0 4px 0 !important;
        line-height: 1.2 !important;
    }
    .right-header-container {
        display: flex;
        align-items: center;
        gap: 16px;
        width: 100%;
        margin-bottom: 12px;
    }
    .right-header-logo-box {
        width: 70px;
        height: 70px;
        flex-shrink: 0;
        display: flex;
        align-items: center;
        justify-content: center;
    }
    .right-header-logo-img {
        width: 100%;
        height: 100%;
        object-fit: contain;
    }
    .right-header-text-box {
        flex-grow: 1;
        display: flex;
        flex-direction: column;
        justify-content: center;
    }
    .right-header-title {
        font-size: 1.35rem !important;
        font-weight: 600 !important;
        margin: 0 !important;
        line-height: 1.2 !important;
    }
    .schedule-detail-card {
        padding: 14px;
        border-radius: 8px;
        margin-bottom: 12px;
        border-left: 5px solid rgba(128, 128, 128, 0.3);
        background-color: rgba(128, 128, 128, 0.05);
    }
    .genre-sport-tint {
        border-left-color: #2e7d32 !important;
        background-color: rgba(46, 125, 50, 0.08) !important;
    }
    .genre-movie-tint {
        border-left-color: #6a1b9a !important;
        background-color: rgba(106, 27, 154, 0.08) !important;
    }
    .match-badge {
        display: inline-block;
        padding: 2px 6px;
        font-size: 0.7rem;
        border-radius: 4px;
        margin-bottom: 4px;
        background-color: rgba(255, 255, 255, 0.15);
        color: #fff;
    }
</style>
""", unsafe_allow_html=True)

# --- Configuration Controls ---
config_col1, config_col2, config_col3 = st.columns(3)

with config_col1:
    tz_options = {
        "UTC / GMT": 0,
        "EST / EDT (UTC-5 / UTC-4)": -4,
        "CST / CDT (UTC-6 / UTC-5)": -5,
        "MST / MDT (UTC-7 / UTC-6)": -6,
        "PST / PDT (UTC-8 / UTC-7)": -7,
        "UK / BST (UTC+0 / UTC+1)": 1,
        "CET / CEST (UTC+1 / UTC+2)": 2
    }
    selected_tz_offset = st.selectbox("Local Timezone Offset", options=list(tz_options.keys()), index=1)
    tz_hours = tz_options[selected_tz_offset]
    target_tz = timezone(timedelta(hours=tz_hours))

with config_col2:
    lookahead_hours = st.selectbox(
        "Future Programming Window",
        options=[0, 2, 4, 6, 8],
        index=1,
        format_func=lambda x: "Always Current Program Only" if x == 0 else f"Current + {x} Hours"
    )

with config_col3:
    per_page_options = [100, 200, 500, 1000, 2000, "All"]
    per_page = st.selectbox("Render Nodes Per Page", options=per_page_options, index=0)

# --- Dual-Ingestion Gateway ---
epg_url_query = st.query_params.get("epg_url", "")
col_input1, col_input2 = st.columns(2)
with col_input1:
    epg_url = st.text_input("Remote EPG URL (Cross-Session Auto-Load)", value=epg_url_query)
with col_input2:
    uploaded_file = st.file_uploader("Or Load Local EPG File", type=["xml", "gz"])

if epg_url and epg_url != epg_url_query:
    st.query_params["epg_url"] = epg_url

@st.cache_data(ttl=3600, show_spinner=False)
def fetch_remote_data(url):
    try:
        response = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, stream=True, timeout=15)
        response.raise_for_status()
        return response.content
    except Exception as e:
        return None

def parse_xmltv_datetime(dt_str, tz_info):
    try:
        parts = dt_str.split()
        base_dt = datetime.strptime(parts[0][:14], "%Y%m%d%H%M%S")
        base_dt = base_dt.replace(tzinfo=timezone.utc)
        return base_dt.astimezone(tz_info)
    except (ValueError, IndexError):
        return None

def get_genre_style_class(category_text):
    if not category_text: return ""
    cat_lower = category_text.lower()
    if "sport" in cat_lower or "sports" in cat_lower: return "genre-sport-tint"
    if "movie" in cat_lower or "film" in cat_lower: return "genre-movie-tint"
    return ""

@st.cache_data(ttl=3600, show_spinner="Parsing EPG Matrix...")
def process_epg_stream(file_bytes, is_gz, max_future_hours, tz_info):
    now_local = datetime.now(timezone.utc).astimezone(tz_info)
    file_obj = io.BytesIO(file_bytes)
    context_stream = gzip.open(file_obj, 'rb') if is_gz else file_obj

    channels, groups, programmes = {}, set(), {}
    context = ET.iterparse(context_stream, events=('end',))
    
    for event, elem in context:
        if elem.tag == 'channel':
            ch_id = elem.get('id')
            display_name = elem.find('display-name').text if elem.find('display-name') is not None else ch_id
            
            icon_tag = elem.find('icon')
            logo_url = icon_tag.get('src') if icon_tag is not None else None
            
            # --- Heuristic Group Fallback Matrix ---
            group_name = None
            group_tag = elem.find('group')
            if group_tag is not None and group_tag.text:
                group_name = group_tag.text.strip()
                
            if not group_name:
                cid_match = re.search(r'\.([a-zA-Z]{2})$', ch_id)
                if cid_match:
                    group_name = cid_match.group(1).upper()
                elif logo_url:
                    logo_match = re.search(r'\.([a-zA-Z]{2})\.(?:png|jpg|jpeg|svg|webp)(?:\?.*)?$', logo_url, re.IGNORECASE)
                    if logo_match:
                        group_name = logo_match.group(1).upper()
            
            channels[ch_id] = {"name": display_name, "group": group_name, "logo": logo_url}
            if group_name: groups.add(group_name)
            programmes[ch_id] = []
            elem.clear()
            
        elif elem.tag == 'programme':
            ch_id = elem.get('channel')
            start_dt = parse_xmltv_datetime(elem.get('start', ''), tz_info)
            stop_dt = parse_xmltv_datetime(elem.get('stop', ''), tz_info)
            
            if start_dt and stop_dt:
                is_current = (start_dt <= now_local < stop_dt)
                is_upcoming = (now_local <= start_dt)
                
                if is_current or is_upcoming:
                    if is_upcoming and (max_future_hours == 0 or (start_dt - now_local).total_seconds() / 3600.0 > max_future_hours):
                        elem.clear()
                        continue
                    
                    title = elem.find('title').text if elem.find('title') is not None else "No Title"
                    desc = elem.find('desc').text if elem.find('desc') is not None else ""
                    categories = [cat.text for cat in elem.findall('category') if cat.text]
                    category_text = " / ".join(categories) if categories else None
                    
                    programmes.setdefault(ch_id, []).append({
                        "start": start_dt, "stop": stop_dt, "title": title,
                        "desc": desc, "genre": category_text, "is_current": is_current
                    })
            elem.clear()

    return sorted(list(groups)), channels, programmes

# Resolve active target file stream
active_data = None
is_gzipped = False
if uploaded_file is not None:
    active_data = uploaded_file.getvalue()
    is_gzipped = uploaded_file.name.endswith('.gz')
elif epg_url:
    fetched = fetch_remote_data(epg_url)
    if fetched:
        active_data = fetched
        is_gzipped = epg_url.endswith('.gz')
    else:
        st.error("Target Remote URL unresolvable or HTTP timeout exceeded.")

if active_data is not None:
    available_groups, channel_map, epg_data = process_epg_stream(active_data, is_gzipped, lookahead_hours, target_tz)
    
    with st.form(key="search_form"):
        st.markdown("### Search & Filter Routing")
        search_vector = st.radio("Search Target Scope", options=["All", "Channels", "Programs", "Descriptions"], horizontal=True)
        
        filter_col1, filter_col2 = st.columns([2, 1])
        with filter_col1:
            search_query = st.text_input("Query String", "").strip().lower()
        with filter_col2:
            selected_group = st.selectbox("Category Group Index", options=["All Groups"] + available_groups)
        st.form_submit_button("Execute Filter Matrix")
    
    now_runtime = datetime.now(timezone.utc).astimezone(target_tz)
    
    # --- Multi-Card Array Generation Matrix ---
    render_nodes = []
    
    for cid, cinfo in channel_map.items():
        if selected_group != "All Groups" and cinfo['group'] != selected_group: 
            continue
            
        has_match = False
        
        if not search_query:
            render_nodes.append({'cid': cid, 'type': 'Standard', 'prog': None})
            continue

        if search_query in cinfo['name'].lower():
            if search_vector in ["All", "Channels"]:
                render_nodes.append({'cid': cid, 'type': 'Channel Match', 'prog': None})
                has_match = True
                
        if search_vector in ["All", "Programs", "Descriptions"]:
            for p in epg_data.get(cid, []):
                t_match = search_query in p['title'].lower()
                d_match = search_query in p['desc'].lower()
                
                if t_match and search_vector in ["All", "Programs"]:
                    render_nodes.append({'cid': cid, 'type': 'Program Match', 'prog': p})
                    has_match = True
                
                if d_match and search_vector in ["All", "Descriptions"]:
                    if not (search_vector == "All" and t_match):
                        render_nodes.append({'cid': cid, 'type': 'Desc Match', 'prog': p})
                        has_match = True

    if not render_nodes:
        st.warning("No active nodes fulfill strict search criteria.")
    else:
        total_nodes = len(render_nodes)
        if per_page == "All":
            page_nodes = render_nodes
        else:
            per_page = int(per_page)
            chunks = (total_nodes + per_page - 1) // per_page
            current_page = st.number_input(f"Page (1 of {chunks})", min_value=1, max_value=chunks, value=1)
            page_nodes = render_nodes[(current_page - 1) * per_page: min(((current_page - 1) * per_page) + per_page, total_nodes)]

        if "active_channel_id" not in st.session_state and page_nodes:
            st.session_state.active_channel_id = page_nodes[0]['cid']

        left_pane, right_pane = st.columns([1.8, 1.4], gap="medium")
        
        with left_pane:
            st.markdown("### 🗺️ Target Directory")
            
            for node in page_nodes:
                cid = node['cid']
                cinfo = channel_map[cid]
                target_prog = node['prog']
                match_type = node['type']
                
                if target_prog is None:
                    schedule = epg_data.get(cid, [])
                    display_prog = next((p for p in schedule if p['is_current']), None)
                else:
                    display_prog = target_prog
                    
                group_badge = f" • {cinfo['group']}" if cinfo['group'] else ""
                is_active = (cid == st.session_state.active_channel_id)
                
                with st.container(border=True):
                    card_logo_col, card_text_col = st.columns([1, 3])
                    
                    with card_logo_col:
                        if cinfo.get("logo"):
                            st.image(cinfo["logo"], use_container_width=True)
                        else:
                            st.subheader("📺")
                            
                    with card_text_col:
                        st.html(f'<p class="dir-ch-title">{cinfo["name"]}</p>')
                        if match_type != "Standard":
                            st.html(f'<span class="match-badge">🔍 {match_type}</span>')
                        if group_badge:
                            st.caption(group_badge)
                            
                    if display_prog:
                        time_prefix = "Now Playing" if display_prog.get('is_current') else f"Upcoming ({display_prog['start'].strftime('%H:%M')})"
                        remaining_mins = int((display_prog['stop'] - now_runtime).total_seconds() // 60) if display_prog.get('is_current') else int((display_prog['stop'] - display_prog['start']).total_seconds() // 60)
                        genre_label = f" [{display_prog['genre']}]" if display_prog['genre'] else ""
                        g_class = get_genre_style_class(display_prog['genre'])
                        
                        st.html(f"""
                        <div class="schedule-detail-card {g_class}" style="padding: 10px; margin-bottom: 10px;">
                            <div style="font-size: 0.9rem; font-weight: bold; margin-bottom: 2px;">{time_prefix}: {display_prog['title']}</div>
                            <div style="font-size: 0.75rem; opacity: 0.8;">⏱️ {remaining_mins} min span{genre_label}</div>
                        </div>
                        """)
                    else:
                        st.caption("ℹ️ No scheduling metadata captured for this window.")
                    
                    btn_key_suffix = str(display_prog['start'].timestamp()) if display_prog else "null"
                    btn_label = "🟢 Active Target View" if is_active else "⚡ Open Main Schedule"
                    if st.button(btn_label, key=f"select_{cid}_{match_type}_{btn_key_suffix}", use_container_width=True, type="primary" if is_active else "secondary"):
                        st.session_state.active_channel_id = cid
                        st.rerun()

        with right_pane:
            active_cid = st.session_state.active_channel_id
            
            if active_cid and active_cid in channel_map:
                active_schedule = epg_data.get(active_cid, [])
                cinfo = channel_map[active_cid]
                
                if cinfo.get("logo"):
                    logo_segment = f'<img src="{cinfo["logo"]}" class="right-header-logo-img" />'
                else:
                    logo_segment = '<span style="font-size: 2.2rem;">📺</span>'
                    
                group_segment = f'<span style="font-size: 0.82rem; opacity: 0.7; font-weight: normal; margin-top: 2px;">Heuristic Index: <b>{cinfo["group"]}</b></span>' if cinfo.get('group') else ''
                
                st.html(f"""
                <div class="right-header-container">
                    <div class="right-header-logo-box">
                        {logo_segment}
                    </div>
                    <div class="right-header-text-box">
                        <h2 class="right-header-title">{cinfo['name']}</h2>
                        {group_segment}
                    </div>
                </div>
                """)
                            
                st.markdown("---")
                
                current_prog = next((p for p in active_schedule if p['is_current']), None)
                future_progs = [p for p in active_schedule if not p['is_current'] and p['start'] > now_runtime]
                
                if current_prog:
                    st.markdown("### 🟢 Active Broadcast")
                    g_class = get_genre_style_class(current_prog['genre'])
                    genre_header = f" | {current_prog['genre']}" if current_prog['genre'] else ""
                    
                    st.html(f"""
                    <div class="schedule-detail-card {g_class}">
                        <h4>⏱️ {current_prog['start'].strftime('%H:%M')} — {current_prog['title']}{genre_header}</h4>
                        <p style="margin-top:8px; line-height:1.5;">{current_prog['desc']}</p>
                    </div>
                    """)
                
                if future_progs:
                    st.markdown("### ⏭️ Pipeline Schedule")
                    for prog in future_progs:
                        g_class = get_genre_style_class(prog['genre'])
                        genre_header = f" | {prog['genre']}" if prog['genre'] else ""
                        
                        st.html(f"""
                        <div class="schedule-detail-card {g_class}">
                            <strong>⏱️ {prog['start'].strftime('%H:%M')} — {prog['title']}</strong>{genre_header}
                            <p style="margin-top:4px; font-size:0.95rem; line-height:1.4; opacity:0.9;">{prog['desc']}</p>
                        </div>
                        """)
                elif not current_prog and not future_progs:
                    st.info("No timeline data loaded for this entity.")
