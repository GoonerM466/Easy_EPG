import gzip
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
    [data-testid="stHorizontalBlock"] { height: 78vh; overflow: hidden; }
    [data-testid="stHorizontalBlock"] > div:nth-child(1) { max-height: 78vh; overflow-y: auto !important; padding-right: 15px; }
    [data-testid="stHorizontalBlock"] > div:nth-child(2) { max-height: 78vh; overflow-y: auto !important; padding-left: 20px; border-left: 1px solid rgba(49, 51, 63, 0.2); }

    .dir-ch-title { font-size: 1.05rem !important; font-weight: 600 !important; margin: 0 0 4px 0 !important; line-height: 1.2 !important; }

    .schedule-detail-card { padding: 14px; border-radius: 8px; margin-bottom: 12px; border-left: 5px solid rgba(128, 128, 128, 0.3); background-color: rgba(128, 128, 128, 0.05); }
    .genre-sport-tint { border-left-color: #2e7d32 !important; background-color: rgba(46, 125, 50, 0.08) !important; }
    .genre-movie-tint { border-left-color: #6a1b9a !important; background-color: rgba(106, 27, 154, 0.08) !important; }
</style>
""", unsafe_allow_html=True)

# --- Configuration Controls ---
config_col1, config_col2, config_col3 = st.columns(3)

with config_col1:
    tz_options = {
        "UTC / GMT": 0, "EST / EDT (UTC-5 / UTC-4)": -4, "CST / CDT (UTC-6 / UTC-5)": -5,
        "MST / MDT (UTC-7 / UTC-6)": -6, "PST / PDT (UTC-8 / UTC-7)": -7,
        "UK / BST (UTC+0 / UTC+1)": 1, "CET / CEST (UTC+1 / UTC+2)": 2
    }
    selected_tz_offset = st.selectbox("Local Timezone Offset", options=list(tz_options.keys()), index=1)
    target_tz = timezone(timedelta(hours=tz_options[selected_tz_offset]))

with config_col2:
    lookahead_hours = st.selectbox("Future Programming Window", options=[0, 2, 4, 6, 8], index=1, format_func=lambda x: "Current Only" if x == 0 else f"Current + {x} Hours")

with config_col3:
    per_page = st.selectbox("Channels Per Page", options=[100, 200, 500, 1000, 2000, "All"], index=0)

uploaded_file = st.file_uploader("Load Local EPG File", type=["xml", "gz"])

def parse_xmltv_datetime(dt_str, tz_info):
    try:
        base_dt = datetime.strptime(dt_str.split()[0][:14], "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
        return base_dt.astimezone(tz_info)
    except: return None

def get_genre_style_class(category_text):
    if not category_text: return ""
    cat_lower = category_text.lower()
    if "sport" in cat_lower: return "genre-sport-tint"
    if "movie" in cat_lower or "film" in cat_lower: return "genre-movie-tint"
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
                    programmes.setdefault(ch_id, []).append({"start": start_dt, "stop": stop_dt, "title": title, "desc": desc, "genre": category_text, "is_current": is_current})
            elem.clear()
    if file_obj.name.endswith('.gz'): context_stream.close()
    for cid in programmes: programmes[cid] = sorted(programmes[cid], key=lambda x: x['start'])
    return sorted(list(groups)), channels, programmes

if uploaded_file is not None:
    available_groups, channel_map, epg_data = process_epg_stream(uploaded_file, lookahead_hours, target_tz)
    with st.form(key="search_form"):
        f1, f2 = st.columns([2, 1])
        with f1: search_query = st.text_input("🔍 Search", "").strip().lower()
        with f2: selected_group = st.selectbox("Filter", options=["All Groups"] + available_groups)
        st.form_submit_button("Search")
    
    now_runtime = datetime.now(timezone.utc).astimezone(target_tz)
    filtered_channels = [cid for cid, cinfo in channel_map.items() if (selected_group == "All Groups" or cinfo['group'] == selected_group) and (not search_query or search_query in cinfo['name'].lower() or any(search_query in p['title'].lower() for p in epg_data.get(cid, [])))]
    
    if not filtered_channels: st.warning("No channels found.")
    else:
        if per_page != "All":
            per_page = int(per_page)
            chunks = (len(filtered_channels) + per_page - 1) // per_page
            current_page = st.number_input(f"Page (1 of {chunks})", min_value=1, max_value=chunks, value=1)
            page_channels = filtered_channels[(current_page - 1) * per_page : current_page * per_page]
        else: page_channels = filtered_channels

        if "active_channel_id" not in st.session_state or st.session_state.active_channel_id not in page_channels:
            st.session_state.active_channel_id = page_channels[0]

        left_pane, right_pane = st.columns([1.8, 1.4], gap="medium")
        with left_pane:
            st.markdown("### 🗺️ Channel Directory")
            for cid in page_channels:
                cinfo, schedule = channel_map[cid], epg_data.get(cid, [])
                current_prog = next((p for p in schedule if p['is_current']), None)
                with st.container(border=True):
                    l_col, t_col = st.columns([1, 3])
                    with l_col:
                        if cinfo.get("logo"): st.image(cinfo["logo"], use_container_width=True)
                        else: st.subheader("📺")
                    with t_col:
                        st.markdown(f'<p class="dir-ch-title">{cinfo["name"]}</p>', unsafe_allow_html=True)
                        if cinfo['group']: st.caption(cinfo['group'])
                    if current_prog: st.markdown(f"**Now:** {current_prog['title']}")
                    if st.button("Select", key=f"btn_{cid}", use_container_width=True, type="primary" if cid == st.session_state.active_channel_id else "secondary"):
                        st.session_state.active_channel_id = cid
                        st.rerun()

        with right_pane:
            cinfo = channel_map[st.session_state.active_channel_id]
            h_cols = st.columns([1, 4])
            with h_cols[0]:
                if cinfo.get("logo"): st.image(cinfo["logo"], use_container_width=True)
                else: st.markdown("## 📺")
            with h_cols[1]:
                st.markdown(f"### {cinfo['name']}")
                if cinfo.get('group'): st.caption(cinfo['group'])
            st.markdown("---")
            
            schedule = epg_data.get(st.session_state.active_channel_id, [])
            current_prog = next((p for p in schedule if p['is_current']), None)
            future_progs = [p for p in schedule if not p['is_current'] and p['start'] > now_runtime]
            
            if current_prog:
                st.markdown("### 🟢 Now Playing")
                st.markdown(f'<div class="schedule-detail-card {get_genre_style_class(current_prog["genre"])}"><h4>⏱️ {current_prog["start"].strftime("%H:%M")} — {current_prog["title"]}</h4><p>{current_prog["desc"]}</p></div>', unsafe_allow_html=True)
            if future_progs:
                st.markdown("### ⏭️ Up Next")
                for p in future_progs:
                    st.markdown(f'<div class="schedule-detail-card {get_genre_style_class(p["genre"])}"><strong>⏱️ {p["start"].strftime("%H:%M")} — {p["title"]}</strong><p>{p["desc"]}</p></div>', unsafe_allow_html=True)
