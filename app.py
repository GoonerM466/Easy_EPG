import gzip
import xml.etree.ElementTree as ET
import streamlit as st
from datetime import datetime, timezone

st.set_page_config(page_title="EPG Viewer", layout="wide")

# --- Security Gateway ---
def check_password():
    """Returns True if the user entered the correct password."""
    if "password_correct" not in st.session_state:
        st.session_state.password_correct = False

    if st.session_state.password_correct:
        return True

    st.subheader("🔒 Access Restricted")
    user_input = st.text_input("Enter Passphrase Key", type="password")
    
    if user_input == st.secrets["access_password"]:
        st.session_state.password_correct = True
        st.rerun()
    elif user_input:
        st.error("Invalid Passphrase Token.")
    return False

if not check_password():
    st.stop()

# --- Post-Authentication Pipeline ---
st.title("📺 Private EPG Viewer")

# Target horizon selection for window filtering
lookahead_hours = st.sidebar.selectbox(
    "Future Programming Window",
    options=[0, 2, 4, 6, 8],
    format_func=lambda x: "Always Current Program Only" if x == 0 else f"Current + {x} Hours"
)

uploaded_file = st.file_uploader("Load Local EPG File", type=["xml", "gz"])

def parse_xmltv_datetime(dt_str):
    """Parses standard XMLTV date string (e.g., '20260719143000 +0000') and converts to local timezone."""
    try:
        # Expected baseline format format: YYYYMMDDhhmmss +/-HHMM
        parts = dt_str.split()
        base_dt = datetime.strptime(parts[0][:14], "%Y%m%d%H%M%S")
        
        # Enforce source UTC definition if marked or assumed
        base_dt = base_dt.replace(tzinfo=timezone.utc)
        
        # Adjust via offset if present in string and not natively UTC zeroed
        if len(parts) > 1 and parts[1] != "+0000":
            # Explicit handling for custom offsets if data drifts from pure UTC
            sign = 1 if parts[1][0] == '+' else -1
            hours = int(parts[1][1:3])
            minutes = int(parts[1][3:5])
            base_dt = base_dt.replace(tzinfo=timezone.utc) # Fallback baseline normalization
            
        # Convert to environment local timezone automatically
        return base_dt.astimezone()
    except (ValueError, IndexError):
        return None

def process_epg_stream(file_obj, max_future_hours):
    """Iteratively parses EPG datasets to bound memory consumption and applies temporal filters."""
    now_local = datetime.now().astimezone()
    
    # Open context stream based on signature compression
    if file_obj.name.endswith('.gz'):
        context_stream = gzip.open(file_obj, 'rb')
    else:
        context_stream = file_obj

    channels = {}
    groups = set()
    programmes = {}

    # Initialize event iterator to process elements on end tags
    context = ET.iterparse(context_stream, events=('end',))
    
    for event, elem in context:
        if elem.tag == 'channel':
            ch_id = elem.get('id')
            display_name = elem.find('display-name').text if elem.find('display-name') is not None else ch_id
            
            group_tag = elem.find('group')
            group_name = group_tag.text if group_tag is not None else "Uncategorized"
            
            channels[ch_id] = {"name": display_name, "group": group_name}
            groups.add(group_name)
            programmes[ch_id] = []
            
            elem.clear() # Prune element subtree from memory
            
        elif elem.tag == 'programme':
            ch_id = elem.get('channel')
            start_raw = elem.get('start', '')
            stop_raw = elem.get('stop', '')
            
            start_dt = parse_xmltv_datetime(start_raw)
            stop_dt = parse_xmltv_datetime(stop_raw)
            
            if start_dt and stop_dt:
                # FILTER CONDITIONS: 
                # 1. Exclude if program already ended before current time
                # 2. Exclude if program starts beyond selected horizon window
                is_current = (start_dt <= now_local < stop_dt)
                
                if is_current or (now_local <= start_dt):
                    if max_future_hours == 0 and not is_current:
                        # Drop if user restricted strictly to active programs
                        elem.clear()
                        continue
                        
                    if max_future_hours > 0:
                        time_delta_hours = (start_dt - now_local).total_seconds() / 3600.0
                        if time_delta_hours > max_future_hours and not is_current:
                            elem.clear()
                            continue
                    
                    title = elem.find('title').text if elem.find('title') is not None else "No Title"
                    desc = elem.find('desc').text if elem.find('desc') is not None else ""
                    
                    programmes.setdefault(ch_id, []).append({
                        "start": start_dt,
                        "stop": stop_dt,
                        "title": title,
                        "desc": desc,
                        "is_current": is_current
                    })
                    
            elem.clear() # Clear reference to maintain low RAM footprint

    # Clean up file handles safely if zipped container
    if file_obj.name.endswith('.gz'):
        context_stream.close()

    # Sort schedules per channel sequentially by start times
    for cid in programmes:
        programmes[cid] = sorted(programmes[cid], key=lambda x: x['start'])

    return sorted(list(groups)), channels, programmes

if uploaded_file is not None:
    available_groups, channel_map, epg_data = process_epg_stream(uploaded_file, lookahead_hours)
    selected_group = st.sidebar.selectbox("Category Group", options=available_groups)
    
    filtered_channels = [cid for cid, cinfo in channel_map.items() if cinfo['group'] == selected_group]
    
    now_runtime = datetime.now().astimezone()
    
    for cid in filtered_channels:
        schedule = epg_data.get(cid, [])
        
        # Isolate target indices for separation
        current_prog = next((p for p in schedule if p['is_current']), None)
        future_progs = [p for p in schedule if not p['is_current'] and p['start'] > now_runtime]
        
        # Build layout label dynamically
        if current_prog:
            remaining_mins = int((current_prog['stop'] - now_runtime).total_seconds() // 60)
            time_str = current_prog['start'].strftime('%H:%M')
            header_string = f"🔹 {channel_map[cid]['name']} — NOW: {time_str} | {current_prog['title']} ({remaining_mins}m left)"
        else:
            header_string = f"🔹 {channel_map[cid]['name']} — [No Information]"
            
        with st.expander(header_string):
            # Display current details at top level inside container
            if current_prog:
                st.markdown(f"### 🟢 Currently Broadcasting")
                st.markdown(f"**⏱️ {current_prog['start'].strftime('%H:%M')}** — **{current_prog['title']}**")
                if current_prog['desc']:
                    st.caption(current_prog['desc'])
                st.markdown("---")
            
            # Sub-render upcoming queue block
            if future_progs:
                st.markdown("### ⏭️ Coming Up Next")
                for prog in future_progs:
                    st.markdown(f"**⏱️ {prog['start'].strftime('%H:%M')}** — **{prog['title']}**")
                    if prog['desc']:
                        st.caption(prog['desc'])
                    st.markdown("---")
            elif not current_prog and not future_progs:
                st.info("No localized scheduling data within selected window.")
