import gzip
import xml.etree.ElementTree as ET
import streamlit as st
from datetime import datetime, timezone, timedelta

st.set_page_config(page_title="Easy EPG", layout="wide")

# --- Security Gateway ---
def check_password():
    """Returns True if the user entered the correct password."""
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

# --- Post-Authentication Pipeline ---
st.title("📺 Easy EPG")

# --- Custom UI Pane Constraints & Global Theme Tints ---
st.markdown("""
<style>
    /* Force independent split-column layout scroll zones */
    [data-testid="stHorizontalBlock"] {
        height: 78vh;
        overflow: hidden;
    }
    
    /* Left Pane: Directory Scroll Layout */
    [data-testid="stHorizontalBlock"] > div:nth-child(1) {
        max-height: 78vh;
        overflow-y: auto !important;
        padding-right: 15px;
    }
    
    /* Right Pane: Detailed Schedule Info Scroll Layout */
    [data-testid="stHorizontalBlock"] > div:nth-child(2) {
        max-height: 78vh;
        overflow-y: auto !important;
        padding-left: 20px;
        border-left: 1px solid rgba(49, 51, 63, 0.2);
    }

    /* Program Guide Info Cards */
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
    per_page = st.selectbox("Channels Per Page", options=per_page_options, index=0)

uploaded_file = st.file_uploader("Load Local EPG File", type=["xml", "gz"])

def parse_xmltv_datetime(dt_str, tz_info):
    try:
        parts = dt_str.split()
        base_dt = datetime.strptime(parts[0][:14], "%Y%m%d%H%M%S")
        base_dt = base_dt.replace(tzinfo=timezone.utc)
        return base_dt.astimezone(tz_info)
    except (ValueError, IndexError):
        return None

def get_genre_style_class(category_text):
    if not category_text:
        return ""
    cat_lower = category_text.lower()
    if "sport" in cat_lower or "sports" in cat_lower:
        return "genre-sport-tint"
    if "movie" in cat_lower or "film" in cat_lower:
        return "genre-movie-tint"
    return ""

def process_epg_stream(file_obj, max_future_hours, tz_info):
    now_local = datetime.now(timezone.utc).astimezone(tz_info)
    context_stream = gzip.open(file_obj, 'rb') if file_obj.name.endswith('.gz') else file_obj

    channels, groups, programmes = {}, set(), {}
    context = ET.iterparse(context_stream, events=('end',))
    
    for event, elem in context:
        if elem.tag == 'channel':
            ch_id = elem.get('id')
            display_name = elem.find('display-name').text if elem.find('display-name') is not None else ch_id
            group_tag = elem.find('group')
            group_name = group_tag.text if group_tag is not None else None
            icon_tag = elem.find('icon')
            logo_url = icon_tag.get('src') if icon_tag is not None else None
            
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

    if file_obj.name.endswith('.gz'): context_stream.close()
    for cid in programmes: programmes[cid] = sorted(programmes[cid], key=lambda x: x['start'])
    return sorted(list(groups)), channels, programmes

if uploaded_file is not None:
    available_groups, channel_map, epg_data = process_epg_stream(uploaded_file, lookahead_hours, target_tz)
    
    with st.form(key="search_form"):
        filter_col1, filter_col2 = st.columns([2, 1])
        with filter_col1:
            search_query = st.text_input("🔍 Search Channel Name or Program Title", "").strip().lower()
        with filter_col2:
            selected_group = st.selectbox("Category Group Filter", options=["All Groups"] + available_groups)
        st.form_submit_button("Search")
    
    now_runtime = datetime.now(timezone.utc).astimezone(target_tz)
    filtered_channels = []
    for cid, cinfo in channel_map.items():
        if selected_group != "All Groups" and cinfo['group'] != selected_group: continue
        if not search_query or search_query in cinfo['name'].lower() or any(search_query in p['title'].lower() for p in epg_data.get(cid, [])):
            filtered_channels.append(cid)
            
    if not filtered_channels:
        st.warning("No matching channels found.")
    else:
        total_channels = len(filtered_channels)
        if per_page == "All":
            page_channels = filtered_channels
        else:
            per_page = int(per_page)
            chunks = (total_channels + per_page - 1) // per_page
            current_page = st.number_input(f"Page (1 of {chunks})", min_value=1, max_value=chunks, value=1)
            page_channels = filtered_channels[(current_page - 1) * per_page: min(((current_page - 1) * per_page) + per_page, total_channels)]

        if "active_channel_id" not in st.session_state and page_channels:
            st.session_state.active_channel_id = page_channels[0]

        left_pane, right_pane = st.columns([1.8, 1.4], gap="medium")
        
        with left_pane:
            st.markdown("### 🗺️ Channel Directory")
            
            for cid in page_channels:
                schedule = epg_data.get(cid, [])
                cinfo = channel_map[cid]
                current_prog = next((p for p in schedule if p['is_current']), None)
                group_badge = f" • {cinfo['group']}" if cinfo['group'] else ""
                
                is_active = (cid == st.session_state.active_channel_id)
                
                # Native structural card element wrapper
                with st.container(border=True):
                    card_logo_col, card_text_col = st.columns([1, 3])
                    
                    with card_logo_col:
                        if cinfo.get("logo"):
                            st.image(cinfo["logo"], use_container_width=True)
                        else:
                            st.subheader("📺")
                            
                    with card_text_col:
                        st.markdown(f"### {cinfo['name']}")
                        if group_badge:
                            st.caption(group_badge)
                            
                    if current_prog:
                        remaining_mins = int((current_prog['stop'] - now_runtime).total_seconds() // 60)
                        genre_label = f" [{current_prog['genre']}]" if current_prog['genre'] else ""
                        st.markdown(f"**Now Playing:** {current_prog['title']}")
                        st.caption(f"⏱️ {remaining_mins} minutes remaining{genre_label}")
                    else:
                        st.caption("ℹ️ No scheduling metadata captured for this window.")
                    
                    # Full-Width Interactive Control Target (100% reliable tap footprint on mobile)
                    btn_label = "🟢 Currently Viewing Channel" if is_active else "⚡ Tap to View Detailed Guide"
                    if st.button(btn_label, key=f"select_ch_{cid}", use_container_width=True, type="primary" if is_active else "secondary"):
                        st.session_state.active_channel_id = cid
                        st.rerun()

        with right_pane:
            active_cid = st.session_state.active_channel_id
            if active_cid not in page_channels and page_channels:
                active_cid = page_channels[0]
                st.session_state.active_channel_id = active_cid
                
            if active_cid and active_cid in channel_map:
                active_schedule = epg_data.get(active_cid, [])
                cinfo = channel_map[active_cid]
                
                st.markdown(f"## 📋 {cinfo['name']}")
                if cinfo['group']: 
                    st.caption(f"Category Group: **{cinfo['group']}**")
                st.markdown("---")
                
                current_prog = next((p for p in active_schedule if p['is_current']), None)
                future_progs = [p for p in active_schedule if not p['is_current'] and p['start'] > now_runtime]
                
                if current_prog:
                    st.markdown("### 🟢 Now Playing")
                    g_class = get_genre_style_class(current_prog['genre'])
                    genre_header = f" | {current_prog['genre']}" if current_prog['genre'] else ""
                    
                    st.markdown(f"""
                    <div class="schedule-detail-card {g_class}">
                        <h4>⏱️ {current_prog['start'].strftime('%H:%M')} — {current_prog['title']}{genre_header}</h4>
                        <p style="margin-top:8px; line-height:1.5;">{current_prog['desc']}</p>
                    </div>
                    """, unsafe_allow_html=True)
                
                if future_progs:
                    st.markdown("### ⏭️ Up Next")
                    for prog in future_progs:
                        g_class = get_genre_style_class(prog['genre'])
                        genre_header = f" | {prog['genre']}" if prog['genre'] else ""
                        
                        st.markdown(f"""
                        <div class="schedule-detail-card {g_class}">
                            <strong>⏱️ {prog['start'].strftime('%H:%M')} — {prog['title']}</strong>{genre_header}
                            <p style="margin-top:4px; font-size:0.95rem; line-height:1.4; opacity:0.9;">{prog['desc']}</p>
                        </div>
                        """, unsafe_allow_html=True)
                elif not current_prog and not future_progs:
                    st.info("No active data timelines mapped for this tracking block.")
