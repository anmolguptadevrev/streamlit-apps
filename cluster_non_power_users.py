"""
Streamlit-based Cluster Explorer Dashboard with Google Drive/Sheets URLs
Simple approach - just paste Google Drive/Sheet links, no API setup needed!

Setup:
    1. Upload your files to Google Drive
    2. Share them (publicly or with your org)
    3. Paste the links in the app
    4. Done!

Local testing:
    cd streamlit_dashboard
    streamlit run app_simple_sheets.py
"""

import streamlit as st
import pandas as pd
import json
import csv
from pathlib import Path
import sys
import requests
from io import StringIO, BytesIO

# Page config
st.set_page_config(
    page_title="Compass - Cluster Explorer",
    page_icon="🧭",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Increase CSV field size limit
csv.field_size_limit(sys.maxsize)

# ============================================================================
# GOOGLE DRIVE/SHEETS URLs - REPLACE THESE WITH YOUR ACTUAL LINKS
# ============================================================================

# Required files
CLUSTER_LABELS_URL = "https://drive.google.com/file/d/1D3uC5kOmHLgWn7X1zFRlfPCYK5_BbQG9/view?usp=sharing"
CLUSTER_ASSIGNMENTS_URL = "https://docs.google.com/spreadsheets/d/1zrLC8DAJ2cVsBCTcTDmpiMPJ4dbKRyf9bq4iBC927xk/edit?gid=1891549065#gid=1891549065"

# Optional files (set to None if not using)
RAW_DATA_URL = None
CLASSIFIED_DATA_URL = "https://docs.google.com/spreadsheets/d/1rKADosJYtZS7ZW0jcb_UqCPStaaGSu1uK9mrB5uVE34/edit?gid=2020214483#gid=2020214483"

# ============================================================================

# Default paths - look in parent directory for data (for local fallback)
DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parent.parent / "output"
RAW_DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "cleaned_data.csv"
CLASSIFIED_DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "classified_facets.csv"

# Custom CSS for better UI
st.markdown("""
<style>
    .stTabs [data-baseweb="tab-list"] {
        gap: 24px;
    }
    .stTabs [data-baseweb="tab"] {
        height: 50px;
        padding-left: 20px;
        padding-right: 20px;
    }
</style>
""", unsafe_allow_html=True)


def convert_google_drive_url(url):
    """Convert Google Drive sharing URL to direct download URL."""
    if not url:
        return None

    # Extract file ID from various Google Drive URL formats
    file_id = None

    if '/file/d/' in url:
        file_id = url.split('/file/d/')[1].split('/')[0]
    elif 'id=' in url:
        file_id = url.split('id=')[1].split('&')[0]
    elif '/open?id=' in url:
        file_id = url.split('/open?id=')[1].split('&')[0]

    if file_id:
        return f"https://drive.google.com/uc?export=download&id={file_id}"

    return url


def convert_google_sheet_url(url):
    """Convert Google Sheets URL to CSV export URL."""
    if not url:
        return None

    # Extract spreadsheet ID
    if '/spreadsheets/d/' in url:
        sheet_id = url.split('/spreadsheets/d/')[1].split('/')[0]
        # Get gid if present (for specific sheet/tab)
        gid = '0'  # Default first sheet
        if 'gid=' in url:
            gid = url.split('gid=')[1].split('&')[0]
        return f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid={gid}"

    return url


@st.cache_data(ttl=300)  # Cache for 5 minutes
def load_from_url(url, file_type='csv'):
    """Load data from a URL."""
    try:
        # Try with confirm parameter for large files
        if 'drive.google.com/uc' in url and 'confirm=' not in url:
            url = url + '&confirm=t'

        response = requests.get(url, timeout=30, allow_redirects=True)
        response.raise_for_status()

        # Check if we got HTML instead of data
        content_type = response.headers.get('Content-Type', '')
        if 'text/html' in content_type and file_type == 'json':
            raise Exception(
                "Received HTML instead of JSON. "
                "The file may not be shared properly. "
                "Go to Google Drive → Right-click file → Share → 'Anyone with the link' → Save. "
                f"Content preview: {response.text[:200]}"
            )

        if file_type == 'csv':
            return pd.read_csv(StringIO(response.text))
        elif file_type == 'json':
            try:
                return json.loads(response.text)
            except json.JSONDecodeError as e:
                raise Exception(
                    f"Invalid JSON format. First 200 chars: {response.text[:200]}... "
                    f"Error: {str(e)}"
                )

    except Exception as e:
        raise Exception(f"Error loading from URL: {str(e)}")


@st.cache_data
def load_cluster_data(output_dir: Path):
    """Load cluster labels and assignments from output directory."""
    labels_path = output_dir / "cluster_labels.json"
    assignments_path = output_dir / "cluster_assignments.csv"

    if not labels_path.exists():
        raise FileNotFoundError(f"Cluster labels not found: {labels_path}")
    if not assignments_path.exists():
        raise FileNotFoundError(f"Cluster assignments not found: {assignments_path}")

    with open(labels_path) as f:
        labels = json.load(f)

    assignments = pd.read_csv(assignments_path)

    return labels, assignments


@st.cache_data
def load_raw_sessions(raw_data_path: Path):
    """Load raw conversation data."""
    if not raw_data_path.exists():
        return None

    df = pd.read_csv(raw_data_path)
    sessions = {}
    for session_id, group in df.groupby('session_id'):
        sessions[session_id] = group.sort_values('update_timestamp').to_dict('records')

    return sessions


@st.cache_data
def load_classifications(classified_path: Path):
    """Load classification data."""
    if not classified_path.exists():
        return None

    df = pd.read_csv(classified_path)
    classifications = {}
    for _, row in df.iterrows():
        key = (str(row['session_id']), str(row.get('facet_idx', 0)))
        classifications[key] = {
            'is_work': row.get('is_work', ''),
            'intent': row.get('intent', '')
        }

    return classifications


def compute_class_stats(facets_df):
    """Compute work/non-work and intent distribution."""
    if len(facets_df) == 0:
        return {
            'work': 0, 'non_work': 0,
            'asking': 0, 'doing': 0, 'expressing': 0,
            'total': 0
        }

    if 'is_work' in facets_df.columns:
        work = ((facets_df['is_work'] == '1') | (facets_df['is_work'] == 1)).sum()
    else:
        work = 0

    total = len(facets_df)

    if 'intent' in facets_df.columns:
        intent_counts = facets_df['intent'].value_counts().to_dict()
    else:
        intent_counts = {}

    return {
        'work': int(work),
        'non_work': int(total - work),
        'asking': int(intent_counts.get('asking', 0)),
        'doing': int(intent_counts.get('doing', 0)),
        'expressing': int(intent_counts.get('expressing', 0)),
        'total': total
    }


def build_hierarchy(labels, assignments_df, classifications):
    """Build hierarchical structure from labels and assignments."""
    levels_list = labels.get("levels", None)

    if classifications:
        def get_class(row):
            key = (str(row['session_id']), str(row.get('facet_idx', 0)))
            cls = classifications.get(key, {})
            return pd.Series({
                'is_work': cls.get('is_work', ''),
                'intent': cls.get('intent', '')
            })

        assignments_df[['is_work', 'intent']] = assignments_df.apply(get_class, axis=1)
    else:
        assignments_df['is_work'] = ''
        assignments_df['intent'] = ''

    if levels_list and len(levels_list) >= 1:
        leaf_level = levels_list[0]
        top_level = levels_list[-1] if len(levels_list) > 1 else None

        leaf_groups = leaf_level.get("groups", {})

        if top_level and len(levels_list) > 1:
            leaf_to_top = {}
            for leaf_id in leaf_groups.keys():
                current_id = int(leaf_id)
                for lvl in levels_list[1:]:
                    parent_map = lvl.get("parent_map", {})
                    current_id = parent_map.get(str(current_id), current_id)
                leaf_to_top[leaf_id] = str(current_id)

            top_groups = top_level.get("groups", {})
            return leaf_groups, top_groups, leaf_to_top, assignments_df
        else:
            return leaf_groups, None, None, assignments_df
    else:
        level2_info = labels.get("level2", {})
        level1_info = labels.get("level1", {})
        level1_map = labels.get("level1_map", {})

        return level2_info, level1_info, level1_map, assignments_df


def display_classification_badge(stats):
    """Display compact classification stats."""
    if not stats or stats.get('total', 0) == 0:
        return

    total = stats['total']
    work_pct = stats['work']/total*100 if total > 0 else 0
    asking_pct = stats['asking']/total*100 if total > 0 else 0
    doing_pct = stats['doing']/total*100 if total > 0 else 0
    expressing_pct = stats['expressing']/total*100 if total > 0 else 0

    st.markdown(
        f"📊 **Classification:** "
        f"Work: {work_pct:.0f}% • "
        f"Asking: {asking_pct:.0f}% • "
        f"Doing: {doing_pct:.0f}% • "
        f"Expressing: {expressing_pct:.0f}%"
    )


def display_facets_table(cluster_facets, raw_sessions, cluster_id):
    """Display facets as an expandable table."""
    if len(cluster_facets) == 0:
        st.info("No facets in this cluster")
        return

    st.markdown(f"**{len(cluster_facets)} facets** in this cluster")

    for idx, (_, facet) in enumerate(cluster_facets.iterrows()):
        session_id = facet['session_id']
        facet_summary = facet.get('facet_summary', '')
        num_turns = facet.get('num_turns', 'N/A')
        token_count = facet.get('raw_token_count', 'N/A')

        is_work = facet.get('is_work', '')
        intent = facet.get('intent', '')

        if is_work == '1':
            work_badge = '<span style="background-color: #28a745; color: white; padding: 4px 10px; border-radius: 4px; font-size: 0.8em; font-weight: 600;">Work</span>'
        elif is_work == '0':
            work_badge = '<span style="background-color: #6c757d; color: white; padding: 4px 10px; border-radius: 4px; font-size: 0.8em; font-weight: 600;">Non-work</span>'
        else:
            work_badge = ''

        intent_colors = {
            'asking': '#007bff',
            'doing': '#6f42c1',
            'expressing': '#dc3545'
        }
        intent_labels = {
            'asking': 'Asking',
            'doing': 'Doing',
            'expressing': 'Expressing'
        }
        if intent and intent.lower() in intent_colors:
            intent_color = intent_colors[intent.lower()]
            intent_label = intent_labels[intent.lower()]
            intent_badge = f'<span style="background-color: {intent_color}; color: white; padding: 4px 10px; border-radius: 4px; font-size: 0.8em; font-weight: 600;">{intent_label}</span>'
        else:
            intent_badge = ''

        with st.container():
            col1, col2, col3, col4 = st.columns([0.55, 0.20, 0.15, 0.10])

            is_truncated = len(facet_summary) > 200
            expand_key = f'expand_{cluster_id}_{session_id}_{idx}'
            is_expanded = st.session_state.get(expand_key, False)

            with col1:
                if is_truncated and not is_expanded:
                    st.markdown(f"**{idx+1}.** {facet_summary[:200]}...")
                else:
                    st.markdown(f"**{idx+1}.** {facet_summary}")

                if is_truncated:
                    if st.button(
                        "↓ Show more" if not is_expanded else "↑ Show less",
                        key=f"toggle_{expand_key}",
                        type="secondary"
                    ):
                        st.session_state[expand_key] = not is_expanded
                        st.rerun()

            with col2:
                if work_badge or intent_badge:
                    st.markdown(f"{work_badge} {intent_badge}", unsafe_allow_html=True)

            with col3:
                st.markdown(f"**{num_turns}** turns  \n**{token_count}** tokens")

            with col4:
                if raw_sessions and session_id in raw_sessions:
                    if st.button("👁️", key=f"view_{cluster_id}_{session_id}_{idx}", help="View full conversation"):
                        st.session_state[f'show_{cluster_id}_{session_id}'] = not st.session_state.get(f'show_{cluster_id}_{session_id}', False)

            if raw_sessions and st.session_state.get(f'show_{cluster_id}_{session_id}', False):
                with st.expander("Full Conversation", expanded=True):
                    for msg in raw_sessions.get(session_id, []):
                        speaker = msg.get('speaker', '')
                        message = msg.get('message', '')
                        if speaker.lower() == 'user':
                            st.markdown(f"**👤 User:** {message}")
                        else:
                            st.markdown(f"**🤖 Assistant:** {message}")

            st.divider()


def main():
    st.title("🧭 Compass - Cluster Explorer")
    st.markdown("*Semantic clustering of conversation data*")

    with st.sidebar:
        st.header("⚙️ Data Source")

        data_source = st.radio(
            "Choose data source:",
            ["Google Drive/Sheets (Configured)", "Local Files"],
            index=0,
            help="Configured: Uses hardcoded URLs in code | Local: Files in repo"
        )

        labels = None
        assignments = None
        raw_sessions = None
        classifications = None

        if data_source == "Google Drive/Sheets (Configured)":
            # Check if URLs are configured
            if "YOUR_FILE_ID_HERE" in CLUSTER_LABELS_URL or "YOUR_SHEET_ID_HERE" in CLUSTER_ASSIGNMENTS_URL:
                st.error("❌ URLs not configured yet!")
                st.info("""
                **To configure:**
                1. Upload files to Google Drive/Sheets
                2. Share them with your org
                3. Edit `app_simple_sheets.py`
                4. Replace the placeholder URLs at the top
                """)
                return

            try:
                with st.spinner("Loading data from Google Drive/Sheets..."):
                    # Convert URLs to direct download/export URLs
                    labels_direct = convert_google_drive_url(CLUSTER_LABELS_URL)
                    assignments_direct = convert_google_sheet_url(CLUSTER_ASSIGNMENTS_URL) if 'spreadsheets' in CLUSTER_ASSIGNMENTS_URL else convert_google_drive_url(CLUSTER_ASSIGNMENTS_URL)

                    # Load required files
                    labels = load_from_url(labels_direct, 'json')
                    assignments = load_from_url(assignments_direct, 'csv')

                    # Load optional files
                    if RAW_DATA_URL and "YOUR_SHEET_ID_HERE" not in RAW_DATA_URL:
                        try:
                            raw_direct = convert_google_sheet_url(RAW_DATA_URL) if 'spreadsheets' in RAW_DATA_URL else convert_google_drive_url(RAW_DATA_URL)
                            raw_df = load_from_url(raw_direct, 'csv')
                            raw_sessions = {}
                            for session_id, group in raw_df.groupby('session_id'):
                                raw_sessions[session_id] = group.sort_values('update_timestamp').to_dict('records')
                        except Exception as e:
                            st.sidebar.warning(f"Could not load raw data: {e}")

                    if CLASSIFIED_DATA_URL and "YOUR_SHEET_ID_HERE" not in CLASSIFIED_DATA_URL:
                        try:
                            class_direct = convert_google_sheet_url(CLASSIFIED_DATA_URL) if 'spreadsheets' in CLASSIFIED_DATA_URL else convert_google_drive_url(CLASSIFIED_DATA_URL)
                            class_df = load_from_url(class_direct, 'csv')
                            classifications = {}
                            for _, row in class_df.iterrows():
                                key = (str(row['session_id']), str(row.get('facet_idx', 0)))
                                classifications[key] = {
                                    'is_work': row.get('is_work', ''),
                                    'intent': row.get('intent', '')
                                }
                        except Exception as e:
                            st.sidebar.warning(f"Could not load classifications: {e}")

                    st.success(f"✅ Loaded {len(assignments)} facets from configured URLs")

            except Exception as e:
                st.error(f"Error loading from URLs: {e}")
                st.info("""
                **Troubleshooting Steps:**

                1. **Share the JSON file properly:**
                   - Go to Google Drive
                   - Right-click `cluster_labels.json`
                   - Click "Share"
                   - Change to "Anyone with the link" (CAN VIEW)
                   - Click "Copy link"
                   - Update the URL in the code

                2. **Alternative: Use Local Files instead:**
                   - Switch to "Local Files" option above
                   - Put your files in `output/` and `data/` directories

                3. **Check file permissions:**
                   - The file must be viewable by anyone with the link
                   - Org-only sharing may require login
                """)

                # Show direct download URL for debugging
                st.code(f"Direct URL attempted: {convert_google_drive_url(CLUSTER_LABELS_URL)}")
                return

        elif data_source == "Local Files":
            try:
                labels, assignments = load_cluster_data(DEFAULT_OUTPUT_DIR)
                raw_sessions = load_raw_sessions(RAW_DATA_PATH)
                classifications = load_classifications(CLASSIFIED_DATA_PATH)
                st.success(f"✅ Loaded {len(assignments)} facets from local files")
            except Exception as e:
                st.error(f"Error loading local data: {e}")
                st.info("Make sure local data files exist in output/ and data/ directories")
                return

    if not (labels and assignments is not None):
        return

    # Build hierarchy
    leaf_groups, top_groups, parent_map, assignments = build_hierarchy(labels, assignments, classifications)

    if 'is_work' in assignments.columns:
        classified_count = (assignments['is_work'] != '').sum()
        if classified_count > 0:
            st.sidebar.success(f"✅ {classified_count} facets classified")

    # Overview metrics
    total_sessions = labels.get("total_sessions", 0)
    total_facets = labels.get("total_facets", 0)
    noise_count = (assignments['cluster'].astype(str) == '-1').sum()
    clustered_count = total_facets - noise_count

    st.header("📊 Overview")

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total Sessions", f"{total_sessions:,}")
    col2.metric("Total Facets", f"{total_facets:,}")
    col3.metric("Clusters", len(leaf_groups))
    col4.metric("Clustered", f"{clustered_count:,} ({(clustered_count / total_facets * 100):.1f}%)")

    if classifications:
        st.markdown("---")
        all_facets = assignments[assignments['cluster'].astype(str) != '-1'].copy()
        overall_stats = compute_class_stats(all_facets)
        display_classification_badge(overall_stats)

    st.markdown("---")

    # Create tabs
    tab1, tab2 = st.tabs(["🗂️ Clusters", "❓ Unclustered"])

    with tab1:
        if top_groups and parent_map:
            st.subheader("Cluster Hierarchy")

            top_categories = sorted(top_groups.keys(), key=lambda x: int(x))

            selected_category = st.selectbox(
                "Select Category",
                top_categories,
                format_func=lambda x: f"{top_groups[x].get('title', f'Category {x}')} ({top_groups[x].get('sessions', 0)} sessions)"
            )

            if selected_category:
                cat_info = top_groups[selected_category]

                st.markdown(f"### {cat_info.get('title', f'Category {selected_category}')}")
                st.markdown(cat_info.get('description', ''))

                col1, col2 = st.columns(2)
                col1.metric("📊 Sessions", cat_info.get('sessions', 0))
                col2.metric("📈 % of Total", f"{cat_info.get('pct_sessions', 0):.1f}%")

                st.markdown("---")

                child_ids = [lid for lid, tid in parent_map.items() if tid == selected_category]

                if child_ids:
                    st.markdown("### 📁 Sub-clusters")

                    for child_id in sorted(child_ids, key=lambda x: int(x)):
                        child_info = leaf_groups.get(child_id, {})

                        with st.expander(
                            f"**{child_info.get('title', f'Cluster {child_id}')}** "
                            f"({child_info.get('sessions', 0)} sessions, {child_info.get('avg_turns', 0):.1f} avg turns)",
                            expanded=False
                        ):
                            st.markdown(f"*{child_info.get('description', '')}*")
                            st.markdown("")

                            col1, col2 = st.columns(2)
                            col1.metric("Sessions", child_info.get('sessions', 0))
                            col2.metric("Avg Turns", f"{child_info.get('avg_turns', 0):.1f}")

                            cluster_facets = assignments[assignments['cluster'].astype(str) == str(child_id)].copy()

                            if classifications and len(cluster_facets) > 0:
                                st.markdown("")
                                stats = compute_class_stats(cluster_facets)
                                display_classification_badge(stats)

                            st.markdown("---")
                            st.markdown("#### 📝 Sample Facets")

                            display_facets_table(cluster_facets, raw_sessions, child_id)

        else:
            st.subheader("All Clusters")

            cluster_ids = sorted(leaf_groups.keys(), key=lambda x: int(x))

            for cluster_id in cluster_ids:
                cluster_info = leaf_groups[cluster_id]

                with st.expander(
                    f"**{cluster_info.get('title', f'Cluster {cluster_id}')}** "
                    f"({cluster_info.get('sessions', 0)} sessions)",
                    expanded=False
                ):
                    st.markdown(f"*{cluster_info.get('description', '')}*")
                    st.markdown("")

                    col1, col2 = st.columns(2)
                    col1.metric("Sessions", cluster_info.get('sessions', 0))
                    col2.metric("% of Total", f"{cluster_info.get('pct_sessions', 0):.1f}%")

                    cluster_facets = assignments[assignments['cluster'].astype(str) == str(cluster_id)].copy()

                    if classifications and len(cluster_facets) > 0:
                        st.markdown("")
                        stats = compute_class_stats(cluster_facets)
                        display_classification_badge(stats)

                    st.markdown("---")
                    st.markdown("#### 📝 Sample Facets")

                    display_facets_table(cluster_facets, raw_sessions, cluster_id)

    with tab2:
        st.subheader("❓ Unclustered Facets")

        unclustered = assignments[assignments['cluster'].astype(str) == '-1'].copy()

        if len(unclustered) > 0:
            st.warning(f"**{len(unclustered)} facets** ({(len(unclustered)/total_facets*100):.1f}% of total) could not be assigned to any cluster")

            if classifications:
                st.markdown("")
                unclustered_stats = compute_class_stats(unclustered)
                display_classification_badge(unclustered_stats)

            st.markdown("---")
            st.markdown("### 📝 Sample Unclustered Facets")

            display_facets_table(unclustered, raw_sessions, "unclustered")
        else:
            st.success("All facets were successfully clustered!")


if __name__ == "__main__":
    main()
