import gzip
import xml.etree.ElementTree as ET
import streamlit as st
from datetime import datetime

st.set_page_config(page_title="EPG Viewer", layout="wide")

# --- Security Gateway ---
def check_password():
    """Returns True if the user entered the correct password."""
    if "password_correct" not in st.session_state:
        st.session_state.password_correct = False

    if st.session_state.password_correct:
        return True

    # Render a clean login container
    st.subheader("🔒 Access Restricted")
    user_input = st.text_input("Enter Passphrase Key", type="password")
    
    # Match input against the encrypted environment secret
    if user_input == st.secrets["access_password"]:
        st.session_state.password_correct = True
        st.rerun()
    elif user_input:
        st.error("Invalid Passphrase Token.")
    return False

# Halt pipeline if password verification fails
if not check_password():
    st.stop()

# --- Post-Authentication Pipeline ---
st.title("📺 Private EPG Viewer")
uploaded_file = st.file_uploader("Load Local EPG File", type=["xml", "gz"])

@st.fragment
def render_epg_view(file_obj):
    if file_obj.name.endswith('.gz'):
        with gzip.open(file_obj, 'rb') as f:
            tree = ET.parse(f)
    else:
        tree = ET.parse(file_obj)
        
    root = tree.getroot()
    channels = {}
    groups = set()
    programmes = {}
    
    # Process structural elements
    for channel in root.findall('channel'):
        ch_id = channel.get('id')
        display_name = channel.find('display-name').text if channel.find('display-name') is not None else ch_id
        
        group_tag = channel.find('group')
        group_name = group_tag.text if group_tag is not None else "Uncategorized"
        
        channels[ch_id] = {"name": display_name, "group": group_name}
        groups.add(group_name)
        programmes[ch_id] = []

    for prog in root.findall('programme'):
        ch_id = prog.get('channel')
        if ch_id in channels:
            title = prog.find('title').text if prog.find('title') is not None else "No Title"
            desc = prog.find('desc').text if prog.find('desc') is not None else ""
            
            start_raw = prog.get('start', '')[:14]
            try:
                start_dt = datetime.strptime(start_raw, "%Y%m%d%H%M%S").strftime("%H:%M")
                time_window = f"{start_dt}"
            except ValueError:
                time_window = "--:--"

            programmes[ch_id].append({"time": time_window, "title": title, "desc": desc})
            
    return sorted(list(groups)), channels, programmes

if uploaded_file is not None:
    available_groups, channel_map, epg_data = render_epg_view(uploaded_file)
    selected_group = st.sidebar.selectbox("Category Group", options=available_groups)
    
    filtered_channels = [cid for cid, cinfo in channel_map.items() if cinfo['group'] == selected_group]
    
    for cid in filtered_channels:
        with st.expander(f"🔹 {channel_map[cid]['name']}"):
            if epg_data[cid]:
                for prog in epg_data[cid]:
                    st.markdown(f"**⏱️ {prog['time']}** — **{prog['title']}**")
                    if prog['desc']:
                        st.caption(prog['desc'])
                    st.markdown("---")
