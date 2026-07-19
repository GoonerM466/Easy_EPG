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

# --- Custom Styling Injection (For Genre Visual Shading Cards) ---
st.markdown("""
<style>
    .genre-card {
        padding: 12px;
        border-radius: 6px;
        margin-bottom: 10px;
        border-left: 5px solid rgba(0,0,0,0.1);
    }
    .genre-sport {
        background-color: #e2f0d9 !important;
        color: #1e4620 !important;
    }
    .genre-movie {
        background-color: #f2e6ff !important;
        color: #4a235a !important;
    }
    .genre-default {
        background-color: #f8f9fa !important;
        color: #212529 !important;
    }
    /* Dark-mode safety adaptations */
    @media (prefers-color-scheme: dark) {
        .genre-sport { background-color: #273e28 !important; color: #e2f0d9 !important; }
        .genre-movie { background-color: #3b254f !important; color: #f2e6ff !important; }
        .genre-default { background-color: #262730 !important; color: #fafafa !important; }
    }
</style>
""", unsafe_allowed_html=True)

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

def get_genre_class_and_text(category_text):
    """Maps XML TV category fields to custom CSS classes and extracts clean text."""
    if not category_text:
        return "genre-default", ""
    
    cat_lower = category_text.lower()
    
    # Sports normalization
    if "sport" in cat_lower or "sports" in cat_lower:
        return "genre-sport", f" | 🏷️ {category_text}"
    # Movies normalization
    if "movie" in cat_lower or "film" in cat_lower:
        return "genre-movie", f" | 🎬 {category_text}"
        
    return "genre-default", f" | 📂 {category_text}"

def process_epg_stream(file_obj, max_future_hours, tz_info):
    now_local = datetime.now(timezone.utc).astimezone(tz_info)
    
    if file_obj.name.endswith('.gz'):
        context_stream = gzip.open(file_obj, 'rb')
    else:
        context_stream = file_obj

    channels = {}
    groups = set()
    programmes = {}

    context = ET.iterparse(context_stream, events=('end',))
    
    for event, elem in context:
        if elem.tag == 'channel':
            ch_id = elem.get('id')
            display_name = elem.find('display-name').text if elem.find('display-name') is not None else ch_id
            
            group_tag = elem.find('group')
            group_name = group_tag.text if group_tag is not None else None
            
            channels[ch_id] = {"name": display_name, "group": group_name}
            if group_name:
                groups.add(group_name)
            programmes[ch_id] = []
            
            elem.clear()
            
        elif elem.tag == 'programme':
            ch_id = elem.get('channel')
            start_raw = elem.get('start', '')
            stop_raw = elem.get('stop', '')
            
            start_dt = parse_xmltv_datetime(start_raw, tz_info)
            stop_dt = parse_xmltv_datetime(stop_raw, tz_info)
            
            if start_dt and stop_dt:
                is_current = (start_dt <= now_local < stop_dt)
                
                if is_current or (now_local <= start_dt):
                    if max_future_hours == 0 and not is_current:
                        elem.clear()
                        continue
                        
                    if max_future_hours > 0:
                        time_delta_hours = (start_dt - now_local).total_seconds() / 3600.0
                        if time_delta_hours > max_future_hours and not is_current:
                            elem.clear()
                            continue
                    
                    title = elem.find('title').text if elem.find('title') is not None else "No Title"
                    desc = elem.find('desc').text if elem.find('desc') is not None else ""
                    
                    # Track Category / Genre metadata
                    category_elem = elem.find('category')
                    category_text = category_elem.text if category_elem is not None else None
                    
                    programmes.setdefault(ch_id, []).append({
                        "start": start_dt,
                        "stop": stop_dt,
                        "title": title,
                        "desc": desc,
                        "genre": category_text,
                        "is_current": is_current
                    })
                    
            elem.clear()

    if file_obj.name.endswith('.gz'):
        context_stream.close()

    for cid in programmes:
        programmes[cid] = sorted(programmes[cid], key=lambda x: x['start'])

    return sorted(list(groups)), channels, programmes

if uploaded_file is not None:
    available_groups, channel_map, epg_data = process_epg_stream(uploaded_file, lookahead_hours, target_tz)
    
    # --- Form-based Explicit Search ---
    with st.form(key="search_form"):
        filter_col1, filter_col2 = st.columns([2, 1])
        with filter_col1:
            search_query = st.text_input("🔍 Search Channel Name or Program Title", "").strip().lower()
        with filter_col2:
            selected_group = st.selectbox("Category Group Filter", options=["All Groups"] + available_groups)
        
        search_submitted = st.form_submit_button("Search")
    
    now_runtime = datetime.now(timezone.utc).astimezone(target_tz)
    
    # Filter channel sets dynamically matching text parameters across the unpaginated dataset
    filtered_channels = []
    for cid, cinfo in channel_map.items():
        if selected_group != "All Groups" and cinfo['group'] != selected_group:
            continue
            
        ch_name_match = search_query in cinfo['name'].lower()
        schedule = epg_data.get(cid, [])
        prog_match = any(search_query in p['title'].lower() for p in schedule)
        
        if not search_query or ch_name_match or prog_match:
            filtered_channels.append(cid)
            
    if not filtered_channels:
        st.warning("No matching channels or program entries found.")
    else:
        total_channels = len(filtered_channels)
        
        if per_page == "All":
            page_channels = filtered_channels
        else:
            per_page = int(per_page)
            chunks = (total_channels + per_page - 1) // per_page
            current_page = st.number_input(f"Page (1 of {chunks})", min_value=1, max_value=chunks, value=1, step=1)
            
            start_idx = (current_page - 1) * per_page
            end_idx = min(start_idx + per_page, total_channels)
            page_channels = filtered_channels[start_idx:end_idx]
            
            st.caption(f"Showing results {start_idx + 1}–{end_idx} out of {total_channels} filtered channels")

        # --- Dynamic Header Construction for Accordion View ---
        header_to_cid_map = {}
        header_options_list = []
        
        for cid in page_channels:
            schedule = epg_data.get(cid, [])
            cinfo = channel_map[cid]
            
            current_prog = next((p for p in schedule if p['is_current']), None)
            group_badge = f" [{cinfo['group']}]" if cinfo['group'] else ""
            
            if current_prog:
                remaining_mins = int((current_prog['stop'] - now_runtime).total_seconds() // 60)
                time_str = current_prog['start'].strftime('%H:%M')
                desc_inline = f" — {current_prog['desc']}" if current_prog['desc'] else ""
                header_string = f"🔹 {cinfo['name']}{group_badge} — NOW: {time_str} | {current_prog['title']} ({remaining_mins}m left){desc_inline}"
            else:
                header_string = f"🔹 {cinfo['name']}{group_badge} — [No Information]"
                
            header_to_cid_map[header_string] = cid
            header_options_list.append(header_string)

        st.markdown("### 🗺️ Channel Directory")
        st.caption("Selecting a new channel closes the previous entry to save screen space.")
        
        # Accordion-enforcer selector component
        selected_header = st.radio(
            "Select Channel to Expand Details",
            options=header_options_list,
            label_visibility="collapsed"
        )
        
        # --- Expanded Content Target Area ---
        if selected_header:
            active_cid = header_to_cid_map[selected_header]
            active_schedule = epg_data.get(active_cid, [])
            
            current_prog = next((p for p in active_schedule if p['is_current']), None)
            future_progs = [p for p in active_schedule if not p['is_current'] and p['start'] > now_runtime]
            
            st.markdown("---")
            
            if current_prog:
                css_class, genre_text = get_genre_class_and_text(current_prog['genre'])
                st.markdown(f"### 🟢 Now Playing")
                st.markdown(f"""
                <div class="genre-card {css_class}">
                    <strong>⏱️ {current_prog['start'].strftime('%H:%M')}</strong> — 
                    <strong>{current_prog['title']}</strong>{genre_text}<br/>
                    <small>{current_prog['desc'] if current_prog['desc'] else ''}</small>
                </div>
                """, unsafe_allowed_html=True)
            
            if future_progs:
                st.markdown(f"### ⏭️ Upcoming")
                for prog in future_progs:
                    css_class, genre_text = get_genre_class_and_text(prog['genre'])
                    st.markdown(f"""
                    <div class="genre-card {css_class}">
                        <strong>⏱️ {prog['start'].strftime('%H:%M')}</strong> — 
                        <strong>{prog['title']}</strong>{genre_text}<br/>
                        <small>{prog['desc'] if prog['desc'] else ''}</small>
                    </div>
                    """, unsafe_allowed_html=True)
            elif not current_prog and not future_progs:
                st.info("No localized scheduling data within selected window.")
