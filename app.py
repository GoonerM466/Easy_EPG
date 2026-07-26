import os
import io
import gzip
import re
import requests
import xml.etree.ElementTree as ET
import streamlit as st
import streamlit.components.v1 as components
from datetime import datetime, timezone, timedelta

st.set_page_config(page_title="Easy EPG", layout="wide")

# --- Procedural Native Component Generation (Absolute Path & Strict Protocol) ---
_COMPONENT_DIR = os.path.abspath("native_select_component")
if not os.path.exists(_COMPONENT_DIR):
    os.makedirs(_COMPONENT_DIR)

_HTML_PAYLOAD = """
<!DOCTYPE html>
<html>
<head>
    <style>
        body { 
            margin: 0; 
            padding: 0; 
            font-family: "Source Sans Pro", sans-serif;
            overflow: hidden; 
        }
        select {
            width: 100%;
            padding: 8px 12px;
            font-size: 16px;
            border-radius: 6px;
            box-sizing: border-box;
            outline: none;
            appearance: auto;
            cursor: pointer;
            transition: border-color 0.2s;
        }
        select:focus {
            border-color: #ff4b4b;
        }
    </style>
</head>
<body>
    <select id="native-dropdown"></select>
    <script>
        const selectEl = document.getElementById("native-dropdown");
        let initialized = false;

        function sendMessageToStreamlit(type, data) {
            window.parent.postMessage({
                isStreamlitMessage: true,
                type: type,
                ...data
            }, "*");
        }

        window.addEventListener("message", function(event) {
            if (event.data.type === "streamlit:render") {
                const args = event.data.args;
                const theme = event.data.theme;
                
                if (theme) {
                    document.body.style.backgroundColor = theme.backgroundColor;
                    selectEl.style.backgroundColor = theme.secondaryBackgroundColor;
                    selectEl.style.color = theme.textColor;
                    selectEl.style.border = `1px solid rgba(128, 128, 128, 0.3)`;
                }

                if (!initialized) {
                    const options = args.options;
                    const default_val = args.default_value;
                    
                    options.forEach(opt => {
                        const el = document.createElement("option");
                        el.value = opt;
                        el.textContent = opt;
                        if (opt === default_val) el.selected = true;
                        selectEl.appendChild(el);
                    });
                    
                    sendMessageToStreamlit("streamlit:setFrameHeight", { height: selectEl.offsetHeight + 10 });
                    initialized = true;
                }
            }
        });

        selectEl.addEventListener("change", function(e) {
            sendMessageToStreamlit("streamlit:setComponentValue", { value: e.target.value });
        });

        sendMessageToStreamlit("streamlit:componentReady", { apiVersion: 1 });
    </script>
</body>
</html>
"""

with open(os.path.join(_COMPONENT_DIR, "index.html"), "w", encoding="utf-8") as f:
    f.write(_HTML_PAYLOAD)

native_selectbox = components.declare_component("native_selectbox", path=_COMPONENT_DIR)

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

st.title("Easy EPG")

# --- Custom UI Pane Constraints & Global Theme Tints ---
st.markdown("""
<style>
    /* Global scroll dampening for containers & touch-event propagation */
    [data-testid="stVerticalBlockBorderWrapper"] {
        overflow: hidden !important;
        height: auto !important;
        max-height: none !important;
    }
    
    [data-testid="stVerticalBlockBorderWrapper"] > div {
        touch-action: pan-y !important;
    }

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
    
    /* Viewport-dependent scalar matrix for right pane header images */
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
        margin-top: 6px;
        background-color: rgba(255, 255, 255, 0.15);
        color: #fff;
    }
</style>
""", unsafe_allow_html=True)

# --- Configuration Controls (URL Query Parameter Sync) ---
with st.expander("⚙️ Settings", expanded=False):
    # Parse URL parameters with fallback defaults
    url_window = st.query_params.get("window", "2")
    try:
        default_window_val = int(url_window)
    except ValueError:
        default_window_val = 2

    url_nodes = st.query_params.get("nodes", "100")
    default_nodes_val = int(url_nodes) if url_nodes != "All" else "All"

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
        lookahead_options = [0, 2, 4, 6, 8, 12, 24, 48, 72, "All"]
        if default_window_val not in lookahead_options:
            default_window_val = 2
        lookahead_index = lookahead_options.index(default_window_val)

        lookahead_hours = st.selectbox(
            "Future Programming Window",
            options=lookahead_options,
            index=lookahead_index,
            format_func=lambda x: "Always Current Program Only" if x == 0 else f"Current + {x} Hours"
        )
        st.query_params["window"] = str(lookahead_hours)

    with config_col3:
        per_page_options = [50, 100, 200, 500, 1000, 2000, "All"]
        if default_nodes_val not in per_page_options:
            default_nodes_val = 100
        per_page_index = per_page_options.index(default_nodes_val)

        per_page = st.selectbox("Render Nodes Per Page", options=per_page_options, index=per_page_index)
        st.query_params["nodes"] = str(per_page)

# --- Dual-Ingestion Gateway ---
with st.expander("📡 Source Config", expanded=False):
    epg_url_query = st.query_params.get("epg_url", "")
    col_input1, col_input2 = st.columns(2)

    with col_input1:
        with st.form(key="url_form"):
            epg_url_input = st.text_input("Remote EPG URL", value=epg_url_query)
            submit_url = st.form_submit_button("Load Remote EPG")
            
            if submit_url and epg_url_input:
                st.query_params["epg_url"] = epg_url_input
                epg_url_query = epg_url_input

    with col_input2:
        uploaded_file = st.file_uploader("Or Load Local EPG File", type=["xml", "gz"])

@st.cache_data(ttl=3600, show_spinner=False)
def fetch_remote_data(url):
    try:
        response = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, stream=True, timeout=20)
        response.raise_for_status()
        return response.content
    except Exception:
        return None

def parse_xmltv_datetime(dt_str, tz_info):
    try:
        parts = dt_str.strip().split()
        time_part = parts[0][:14]
        dt = datetime.strptime(time_part, "%Y%m%d%H%M%S")
        
        if len(parts) > 1 and len(parts[1]) == 5:
            offset_str = parts[1]
            hours = int(offset_str[1:3])
            minutes = int(offset_str[3:5])
            sign = -1 if offset_str[0] == '-' else 1
            src_tz = timezone(sign * timedelta(hours=hours, minutes=minutes))
            dt = dt.replace(tzinfo=src_tz)
        else:
            dt = dt.replace(tzinfo=tz_info)
            
        return dt.astimezone(tz_info)
    except (ValueError, IndexError):
        return None

def get_genre_style_class(category_text):
    if not category_text: return ""
    cat_lower = category_text.lower()
    if "sport" in cat_lower or "sports" in cat_lower: return "genre-sport-tint"
    if "movie" in cat_lower or "film" in cat_lower: return "genre-movie-tint"
    return ""

@st.cache_data(ttl=3600, show_spinner="Parsing EPG...")
def process_epg_stream(file_bytes, is_gz, tz_info):
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
                title = elem.find('title').text if elem.find('title') is not None else "No Title"
                desc = elem.find('desc').text if elem.find('desc') is not None else ""
                
                raw_categories = [cat.text for cat in elem.findall('category') if cat.text]
                clean_categories = []
                for rc in raw_categories:
                    parts = [p.strip() for p in rc.split('/')]
                    for p in parts:
                        if p:
                            clean_categories.append(p.title())
                            
                category_text = " / ".join(clean_categories) if clean_categories else None
                
                programmes.setdefault(ch_id, []).append({
                    "start": start_dt, "stop": stop_dt, "title": title,
                    "desc": desc, "genre": category_text, "genre_list": clean_categories
                })
            elem.clear()

    return sorted(list(groups)), channels, programmes

# --- Active Target Data Stream Resolution ---
active_data = None
is_gzipped = False

if uploaded_file is not None:
    active_data = uploaded_file.getvalue()
    is_gzipped = active_data.startswith(b'\x1f\x8b')
elif epg_url_query:
    fetched = fetch_remote_data(epg_url_query)
    if fetched:
        active_data = fetched
        is_gzipped = active_data.startswith(b'\x1f\x8b')
    else:
        st.error("Target Remote URL unresolvable or HTTP timeout exceeded.")

if active_data is not None:
    available_groups, channel_map, epg_raw = process_epg_stream(active_data, is_gzipped, target_tz)
    now_runtime = datetime.now(timezone.utc).astimezone(target_tz)
    
    # --- Dynamic Time Window Filter Pass & Active Taxonomic Extraction ---
    epg_data = {}
    active_genres_set = set()
    
    for cid, progs in epg_raw.items():
        filtered_progs = []
        for p in progs:
            is_current = (p['start'] <= now_runtime < p['stop'])
            is_upcoming = (now_runtime <= p['start'])
            
            if is_current or is_upcoming:
                if is_upcoming and (lookahead_hours > 0) and ((p['start'] - now_runtime).total_seconds() / 3600.0 > lookahead_hours):
                    continue
                p_copy = dict(p)
                p_copy['is_current'] = is_current
                filtered_progs.append(p_copy)
                
                for g in p_copy.get('genre_list', []):
                    active_genres_set.add(g)
                    
        epg_data[cid] = filtered_progs

    available_genres = sorted(list(active_genres_set), key=str.lower)

    # --- Persistent Rendering Nodes (Native Component Vectors) ---
    pers_col1, pers_col2 = st.columns(2)
    
    group_options = ["All Groups"] + available_groups
    genre_options = ["All Genres"] + available_genres

    with pers_col1:
        st.markdown("<p style='font-size: 0.85rem; margin-bottom: 2px;'>Category Group Index</p>", unsafe_allow_html=True)
        raw_group = native_selectbox(options=group_options, default_value="All Groups", key="native_group")
        selected_group = raw_group if raw_group is not None else "All Groups"

    with pers_col2:
        st.markdown("<p style='font-size: 0.85rem; margin-bottom: 2px;'>Genre Classification Filter</p>", unsafe_allow_html=True)
        raw_genre = native_selectbox(options=genre_options, default_value="All Genres", key="native_genre")
        selected_genre = raw_genre if raw_genre is not None else "All Genres"

    with st.expander("🔍 Search & Filter", expanded=False):
        with st.form(key="search_form"):
            search_vector = st.radio("Search Target Scope", options=["All", "Channels", "Programs", "Descriptions", "Genre"], horizontal=True)
            search_query = st.text_input("Query String", "").strip().lower()
            st.form_submit_button("Execute Search")
            
    # --- Matrix Evaluation Loop ---
    render_nodes = []
    is_active_genre = (selected_genre != "All Genres")
    is_active_search = bool(search_query)
    
    for cid, cinfo in channel_map.items():
        if selected_group != "All Groups" and cinfo['group'] != selected_group: 
            continue
            
        if not is_active_search and not is_active_genre:
            render_nodes.append({'cid': cid, 'type': 'Standard', 'prog': None})
            continue

        if is_active_search and not is_active_genre:
            if search_vector in ["All", "Channels"] and search_query in cinfo['name'].lower():
                render_nodes.append({'cid': cid, 'type': 'Channel Match', 'prog': None})

        for p in epg_data.get(cid, []):
            genre_pass = True
            search_pass = True
            match_labels = []
            
            if is_active_genre:
                if selected_genre not in p.get('genre_list', []):
                    genre_pass = False
                else:
                    match_labels.append("Genre Match")
                    
            if is_active_search:
                t_match = search_query in p['title'].lower()
                d_match = search_query in p['desc'].lower()
                g_match = p['genre'] is not None and search_query in p['genre'].lower()
                
                if search_vector == "All":
                    if not (t_match or d_match or g_match):
                        search_pass = False
                    else:
                        if t_match: match_labels.append('Title Match')
                        elif d_match: match_labels.append('Description Match')
                        elif g_match: match_labels.append('Genre Match')
                elif search_vector == "Programs":
                    if not t_match: search_pass = False
                    else: match_labels.append('Title Match')
                elif search_vector == "Descriptions":
                    if not d_match: search_pass = False
                    else: match_labels.append('Description Match')
                elif search_vector == "Genre":
                    if not g_match: search_pass = False
                    else: match_labels.append('Genre Match')
                elif search_vector == "Channels":
                     if search_query not in cinfo['name'].lower(): search_pass = False
                     else: match_labels.append('Channel Match')

            if genre_pass and search_pass:
                final_type = " | ".join(dict.fromkeys(match_labels)) if match_labels else "Filtered"
                render_nodes.append({'cid': cid, 'type': final_type, 'prog': p})

    if is_active_search or is_active_genre:
        def get_sort_datetime(node):
            if node['prog']:
                return node['prog']['start']
            return datetime.max.replace(tzinfo=timezone.utc)
        render_nodes.sort(key=get_sort_datetime)

    # --- State Desynchronization Resolver & Filter Hash Evaluator ---
    current_filter_hash = hash((selected_group, selected_genre, search_query, search_vector))
    filter_mutation_detected = False
    
    if "system_filter_hash" not in st.session_state:
        st.session_state.system_filter_hash = current_filter_hash
    elif st.session_state.system_filter_hash != current_filter_hash:
        filter_mutation_detected = True
        st.session_state.system_filter_hash = current_filter_hash

    if not render_nodes:
        st.warning("No Results Found...")
        st.session_state.active_channel_id = None
    else:
        total_nodes = len(render_nodes)
        if per_page == "All":
            page_nodes = render_nodes
        else:
            per_page = int(per_page)
            chunks = (total_nodes + per_page - 1) // per_page
            current_page = st.number_input(f"Page (1 of {chunks})", min_value=1, max_value=chunks, value=1)
            page_nodes = render_nodes[(current_page - 1) * per_page: min(((current_page - 1) * per_page) + per_page, total_nodes)]

        # Hard reset pointer state on matrix mutation
        if filter_mutation_detected or "active_channel_id" not in st.session_state:
            st.session_state.active_channel_id = page_nodes[0]['cid']
            
        # Hard reset left pane Y-axis scroll mapping
        if filter_mutation_detected:
            st.html("""
            <script>
                const targetDoc = window.parent || window;
                const leftPane = targetDoc.document.querySelector('[data-testid="stHorizontalBlock"] > div:nth-child(1)');
                if (leftPane) {
                    leftPane.scrollTop = 0;
                }
            </script>
            """)

        left_pane, right_pane = st.columns([1.8, 1.4], gap="medium")
        
        with left_pane:
            st.markdown("### Channel Directory")
            
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
                    logo_segment = f'<img src="{cinfo["logo"]}" style="max-width: 100%; max-height: 45px; object-fit: contain; display: block;" />' if cinfo.get("logo") else '<span style="font-size: 1.8rem;">📺</span>'
                    badge_segment = f'<span class="match-badge">🔍 {match_type}</span>' if match_type != "Standard" else ""
                    
                    st.html(f"""
                    <div style="display: flex; flex-direction: row; align-items: center; gap: 14px; margin-bottom: 12px; overflow: hidden;">
                        <div style="flex-shrink: 0; width: 80px; display: flex; align-items: center; justify-content: center;">
                            {logo_segment}
                        </div>
                        <div style="display: flex; flex-direction: column; overflow: hidden; flex-grow: 1;">
                            <div style="font-weight: 600; font-size: 1.15rem; line-height: 1.2; white-space: normal; word-wrap: break-word;">{cinfo['name']}</div>
                            <div style="font-size: 0.85rem; color: #888; margin-top: 4px;">{group_badge}</div>
                            {badge_segment}
                        </div>
                    </div>
                    """)
                            
                    if display_prog:
                        time_prefix = "Now Playing" if display_prog.get('is_current') else f"Upcoming ({display_prog['start'].strftime('%H:%M')})"
                        
                        if display_prog.get('is_current'):
                            remaining_sec = (display_prog['stop'] - now_runtime).total_seconds()
                            remaining_mins = max(0, int(remaining_sec // 60))
                            span_label = f"⏱️ {remaining_mins} min left"
                        else:
                            total_mins = int((display_prog['stop'] - display_prog['start']).total_seconds() // 60)
                            span_label = f"⏱️ {total_mins} min span"
                            
                        g_class = get_genre_style_class(display_prog['genre'])
                        genre_html = f'<div style="font-size: 0.85rem; font-weight: 400; margin-top: 4px; opacity: 0.85;">[{display_prog["genre"]}]</div>' if display_prog['genre'] else ""
                        
                        st.html(f"""
                        <div class="schedule-detail-card {g_class}" style="padding: 10px; margin-bottom: 10px;">
                            <div style="font-size: 0.95rem; font-weight: bold;">{time_prefix} - {display_prog['title']}</div>
                            {genre_html}
                            <div style="font-size: 0.8rem; opacity: 0.8; margin-top: 6px;">{span_label}</div>
                        </div>
                        """)
                    else:
                        st.caption("ℹ️ No Program Info...")
                    
                    btn_key_suffix = str(display_prog['start'].timestamp()) if display_prog else "null"
                    btn_label = "🟢 Channel Selected" if is_active else "Open Channel Schedule"
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
                    
                group_segment = f'<span style="font-size: 0.82rem; opacity: 0.7; font-weight: normal; margin-top: 2px;">• <b>{cinfo["group"]}</b></span>' if cinfo.get('group') else ''
                
                st.html(f"""
                <div class="right-header-container">
                    <div class="right-header-logo-box">
                        {logo_segment}
                    </div>
                    <div class="right-header-text-box">
                        <div class="right-header-title">{cinfo['name']}</div>
                        {group_segment}
                    </div>
                </div>
                """)
                            
                st.markdown("---")
                
                current_prog = next((p for p in active_schedule if p['is_current']), None)
                future_progs = [p for p in active_schedule if not p['is_current'] and p['start'] > now_runtime]
                
                if current_prog:
                    st.markdown("### 🟢 Now Playing")
                    g_class = get_genre_style_class(current_prog['genre'])
                    genre_html = f'<div style="font-size: 0.85rem; font-weight: 400; margin-top: 4px; opacity: 0.85;">[{current_prog["genre"]}]</div>' if current_prog['genre'] else ""
                    
                    st.html(f"""
                    <div class="schedule-detail-card {g_class}">
                        <div style="font-weight: bold; font-size: 1.05rem;">{current_prog['start'].strftime('%H:%M')} - {current_prog['title']}</div>
                        {genre_html}
                        <div style="margin-top: 8px; line-height: 1.5; font-size: 0.95rem;">{current_prog['desc']}</div>
                    </div>
                    """)
                
                if future_progs:
                    st.markdown("### ⏭️ Upcoming Programs")
                    for prog in future_progs:
                        g_class = get_genre_style_class(prog['genre'])
                        genre_html = f'<div style="font-size: 0.85rem; font-weight: 400; margin-top: 4px; opacity: 0.85;">[{prog["genre"]}]</div>' if prog['genre'] else ""
                        
                        st.html(f"""
                        <div class="schedule-detail-card {g_class}">
                            <div style="font-weight: bold; font-size: 1.05rem;">{prog['start'].strftime('%H:%M')} - {prog['title']}</div>
                            {genre_html}
                            <div style="margin-top: 6px; font-size: 0.95rem; line-height: 1.4; opacity: 0.9;">{prog['desc']}</div>
                        </div>
                        """)
                elif not current_prog and not future_progs:
                    st.info("No timeline data loaded for this entity.")
