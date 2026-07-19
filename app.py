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

# --- Custom UI Engine Styling Injection ---
st.markdown("""
<style>
    /* Force independent layout scrolling zones */
    [data-testid="stHorizontalBlock"] {
        height: 78vh;
        overflow: hidden;
    }
    
    /* Left Pane: Directory Scroll */
    [data-testid="stHorizontalBlock"] > div:nth-child(1) {
        max-height: 78vh;
        overflow-y: auto !important;
        padding-right: 15px;
    }
    
    /* Right Pane: Program Details Scroll */
    [data-testid="stHorizontalBlock"] > div:nth-child(2) {
        max-height: 78vh;
        overflow-y: auto !important;
        padding-left: 20px;
        border-left: 1px solid rgba(49, 51, 63, 0.2);
    }

    /* Absolute Overlay Container for Tap Zones */
    .clickable-card-wrapper {
        position: relative;
        width: 100%;
        margin-bottom: 16px;
    }

    /* The visual block rendered via Markdown */
    .ch-row-card {
        width: 100%;
        padding: 16px;
        border-radius: 10px;
        box-sizing: border-box;
        transition: background-color 0.2s ease, border-color 0.2s ease;
        display: flex;
        align-items: flex-start;
        gap: 16px;
    }
    
    /* Selection Borders wrapped cleanly around the entire structure */
    .card-active {
        border: 2px solid currentColor !important;
        background-color: rgba(128, 128, 128, 0.08) !important;
    }
    .card-normal {
        border: 2px solid rgba(128, 128, 128, 0.15) !important;
        background-color: transparent;
    }

    /* Force the Streamlit button to fill the card container completely and become invisible */
    .clickable-card-wrapper div.stButton {
        position: absolute;
        top: 0;
        left: 0;
        width: 100%;
        height: 100%;
        z-index: 10;
    }
    .clickable-card-wrapper div.stButton > button {
        width: 100% !important;
        height: 100% !important;
        background-color: transparent !important;
        border: none !important;
        color: transparent !important;
        padding: 0 !important;
        margin: 0 !important;
    }
    .clickable-card-wrapper div.stButton > button:hover {
        background-color: rgba(128, 128, 128, 0.04) !important;
    }
    
    /* Layout components inside the card */
    .card-logo-frame {
        flex-shrink: 0;
        width: 84px;
        display: flex;
        align-items: center;
        justify-content: center;
    }
    .card-logo-img {
        width: 84px;
        height: auto;
        max-height: 70px;
        object-fit: contain;
    }
    .card-logo-fallback {
        width: 84px;
        height: 60px;
        background: rgba(49, 51, 63, 0.1);
        border-radius: 4px;
    }
    .card-content-frame {
        flex-grow: 1;
    }
    .card-ch-title {
        font-size: 1.15rem;
        font-weight: 700;
        line-height: 1.3;
        margin-bottom: 8px;
    }
    
    /* Expanded padding configuration to prevent text layout truncation */
    .card-live-prog-box {
        padding: 12px 14px;
        border-radius: 6px;
        border-left: 4px solid rgba(0,0,0,0.15);
        font-size: 1.02rem;
        line-height: 1.45;
        display: block;
        word-wrap: break-word;
        box-sizing: border-box;
    }
    
    /* Detailed Program Section Styles */
    .prog-header-title {
        font-size: 1.45rem !important;
        font-weight: 700;
        margin-bottom: 4px;
        display: flex;
        align-items: center;
        gap: 8px;
    }
    .genre-card {
        padding: 12px 14px;
        border-radius: 6px;
        margin-bottom: 10px;
        border-left: 5px solid rgba(0,0,0,0.1);
        font-size: 1.0rem !important;
    }
    .genre-card strong {
        font-size: 1.05rem !important;
    }

    /* Universal Shading Maps */
    .genre-sport { background-color: #e2f0d9 !important; color: #1e4620 !important; }
    .genre-movie { background-color: #f2e6ff !important; color: #4a235a !important; }
    .genre-default { background-color: #f8f9fa !important; color: #212529 !important; }

    @media (prefers-color-scheme: dark) {
        .genre-sport { background-color: #213a22 !important; color: #e2f0d9 !important; }
        .genre-movie { background-color: #2f1d3f !important; color: #f2e6ff !important; }
        .genre-default { background-color: #262730 !important; color: #fafafa !important; }
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

def get_genre_info(category_text):
    if not category_text:
        return "genre-default", ""
    cat_lower = category_text.lower()
    if "sport" in cat_lower or "sports" in cat_lower:
        return "genre-sport", f" | ({category_text})"
    if "movie" in cat_lower or "film" in cat_lower:
        return "genre-movie", f" | ({category_text})"
    return "genre-default", f" | ({category_text})"

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

        if "active_channel_id" not in st.session_state:
            st.session_state.active_channel_id = page_channels[0] if page_channels else None

        left_pane, right_pane = st.columns([2, 1.2], gap="medium")
        
        with left_pane:
            st.markdown("### 🗺️ Channel Directory")
            
            for cid in page_channels:
                schedule = epg_data.get(cid, [])
                cinfo = channel_map[cid]
                current_prog = next((p for p in schedule if p['is_current']), None)
                group_badge = f" [{cinfo['group']}]" if cinfo['group'] else ""
                
                is_active = (cid == st.session_state.active_channel_id)
                card_state_class = "card-active" if is_active else "card-normal"
                
                if cinfo.get("logo"):
                    logo_html = f'<div class="card-logo-frame"><img src="{cinfo["logo"]}" class="card-logo-img"/></div>'
                else:
                    logo_html = '<div class="card-logo-frame"><div class="card-logo-fallback"></div></div>'
                
                if current_prog:
                    remaining_mins = int((current_prog['stop'] - now_runtime).total_seconds() // 60)
                    bg_class, genre_text = get_genre_info(current_prog['genre'])
                    prog_html = f"""
                    <div class="card-live-prog-box {bg_class}">
                        Now: {current_prog['title']} — {remaining_mins}m left{genre_text}
                    </div>
                    """
                else:
                    prog_html = '<div class="card-live-prog-box genre-default">[No Information]</div>'
                
                # Render structural markup card and overlay transparent button container sequentially
                st.markdown(f"""
                <div class="clickable-card-wrapper">
                    <div class="ch-row-card {card_state_class}">
                        {logo_html}
                        <div class="card-content-frame">
                            <div class="card-ch-title">{cinfo['name']}{group_badge}</div>
                            {prog_html}
                        </div>
                    </div>
                </div>
                """, unsafe_allow_html=True)
                
                # Position button precisely on top of the DOM layout wrapper object boundary
                if st.button("", key=f"overlay_click_{cid}"):
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
                
                logo_header_html = f'<img src="{cinfo["logo"]}" style="width:48px; height:48px; object-fit:contain; vertical-align:middle; margin-right:8px; border-radius:4px;"/> | {cinfo["name"]}' if cinfo.get("logo") else f'📺 {cinfo["name"]}'
                st.markdown(f'<div class="prog-header-title">{logo_header_html}</div>', unsafe_allow_html=True)
                if cinfo['group']: st.caption(f"Group Category: **{cinfo['group']}**")
                st.markdown("---")
                
                current_prog = next((p for p in active_schedule if p['is_current']), None)
                future_progs = [p for p in active_schedule if not p['is_current'] and p['start'] > now_runtime]
                
                if current_prog:
                    bg_class, genre_text = get_genre_info(current_prog['genre'])
                    st.markdown(f"### 🟢 Now Playing")
                    st.markdown(f'<div class="genre-card {bg_class}"><strong>⏱️ {current_prog["start"].strftime("%H:%M")}</strong> — <strong>{current_prog["title"]}</strong>{genre_text}<br/><div style="margin-top:6px;">{current_prog["desc"]}</div></div>', unsafe_allow_html=True)
                
                if future_progs:
                    st.markdown(f"### ⏭️ Upcoming")
                    for prog in future_progs:
                        bg_class, genre_text = get_genre_info(prog['genre'])
                        st.markdown(f'<div class="genre-card {bg_class}"><strong>⏱️ {prog["start"].strftime("%H:%M")}</strong> — <strong>{prog["title"]}</strong>{genre_text}<br/><div style="margin-top:6px;">{prog["desc"]}</div></div>', unsafe_allow_html=True)
