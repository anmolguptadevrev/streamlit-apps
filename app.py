"""
Streamlit-based Cluster Explorer Dashboard
Replaces the custom HTTP server with an interactive Streamlit app.

Deployment:
    1. Push to GitHub
    2. Deploy on streamlit.io/cloud (free)
    3. Share the public URL

Local testing:
    cd streamlit_dashboard
    streamlit run app.py
"""

import streamlit as st
import pandas as pd
import json
import csv
from pathlib import Path
import sys

# Page config
st.set_page_config(
    page_title="Compass - Cluster Explorer",
    page_icon="🧭",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Increase CSV field size limit
csv.field_size_limit(sys.maxsize)

# Default paths - look in parent directory for data
DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parent.parent / "output"
RAW_DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "cleaned_data.csv"
CLASSIFIED_DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "classified_facets.csv"

# Custom CSS for better UI - works with both light and dark themes
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
    # Group by session_id
    sessions = {}
    for session_id, group in df.groupby('session_id'):
        sessions[session_id] = group.sort_values('update_timestamp').to_dict('records')

    return sessions


@st.cache_data
def load_classifications(classified_path: Path):
    """Load classification data (work/non-work, intent)."""
    if not classified_path.exists():
        return None

    df = pd.read_csv(classified_path)
    # Create composite key
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

    # Handle both string and numeric is_work values
    if 'is_work' in facets_df.columns:
        work = ((facets_df['is_work'] == '1') | (facets_df['is_work'] == 1)).sum()
    else:
        work = 0

    total = len(facets_df)

    # Count intents
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
    """Build hierarchical structure from labels and assignments. Returns hierarchy info and modified assignments."""
    levels_list = labels.get("levels", None)

    # Add classification info to assignments (create a copy to avoid issues)
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
        # Add empty columns if no classifications
        assignments_df['is_work'] = ''
        assignments_df['intent'] = ''

    if levels_list and len(levels_list) >= 1:
        # New recursive hierarchy format
        leaf_level = levels_list[0]
        top_level = levels_list[-1] if len(levels_list) > 1 else None

        leaf_groups = leaf_level.get("groups", {})

        if top_level and len(levels_list) > 1:
            # Build parent mapping
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
            # Only leaves
            return leaf_groups, None, None, assignments_df
    else:
        # Legacy format
        level2_info = labels.get("level2", {})
        level1_info = labels.get("level1", {})
        level1_map = labels.get("level1_map", {})

        return level2_info, level1_info, level1_map, assignments_df


def display_classification_badge(stats):
    """Display compact classification stats as inline badges."""
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
    """Display facets as an expandable table with conversation view."""
    if len(cluster_facets) == 0:
        st.info("No facets in this cluster")
        return

    st.markdown(f"**{len(cluster_facets)} facets** in this cluster")

    # Show ALL facets (no limit)
    for idx, (_, facet) in enumerate(cluster_facets.iterrows()):
        session_id = facet['session_id']
        facet_summary = facet.get('facet_summary', '')
        num_turns = facet.get('num_turns', 'N/A')
        token_count = facet.get('raw_token_count', 'N/A')

        # Get classification labels
        is_work = facet.get('is_work', '')
        intent = facet.get('intent', '')

        # Create work badge
        if is_work == '1':
            work_badge = '<span style="background-color: #28a745; color: white; padding: 4px 10px; border-radius: 4px; font-size: 0.8em; font-weight: 600;">Work</span>'
        elif is_work == '0':
            work_badge = '<span style="background-color: #6c757d; color: white; padding: 4px 10px; border-radius: 4px; font-size: 0.8em; font-weight: 600;">Non-work</span>'
        else:
            work_badge = ''

        # Create intent badge
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

        # Create a clean display
        with st.container():
            # Split into columns: summary (60%), badges (20%), metadata (15%), button (5%)
            col1, col2, col3, col4 = st.columns([0.55, 0.20, 0.15, 0.10])

            is_truncated = len(facet_summary) > 200
            expand_key = f'expand_{cluster_id}_{session_id}_{idx}'
            is_expanded = st.session_state.get(expand_key, False)

            with col1:
                # Summary text with expand/collapse
                if is_truncated and not is_expanded:
                    st.markdown(f"**{idx+1}.** {facet_summary[:200]}...")
                else:
                    st.markdown(f"**{idx+1}.** {facet_summary}")

                # Show expand/collapse link for truncated text
                if is_truncated:
                    if st.button(
                        "↓ Show more" if not is_expanded else "↑ Show less",
                        key=f"toggle_{expand_key}",
                        type="secondary"
                    ):
                        st.session_state[expand_key] = not is_expanded
                        st.rerun()

            with col2:
                # Badges
                if work_badge or intent_badge:
                    st.markdown(f"{work_badge} {intent_badge}", unsafe_allow_html=True)

            with col3:
                # Metadata
                st.markdown(f"**{num_turns}** turns  \n**{token_count}** tokens")

            with col4:
                if raw_sessions and session_id in raw_sessions:
                    if st.button("👁️", key=f"view_{cluster_id}_{session_id}_{idx}", help="View full conversation"):
                        st.session_state[f'show_{cluster_id}_{session_id}'] = not st.session_state.get(f'show_{cluster_id}_{session_id}', False)

            # Show full conversation if toggled
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

    # Sidebar for data source selection
    with st.sidebar:
        st.header("⚙️ Data Source")

        use_upload = st.checkbox("Upload custom data files", value=False)

        if use_upload:
            st.info("Upload your clustering output files:")

            labels_file = st.file_uploader(
                "cluster_labels.json",
                type=['json'],
                help="JSON file with cluster hierarchy and labels"
            )

            assignments_file = st.file_uploader(
                "cluster_assignments.csv",
                type=['csv'],
                help="CSV file with facet-to-cluster assignments"
            )

            raw_data_file = st.file_uploader(
                "cleaned_data.csv (optional)",
                type=['csv'],
                help="Optional: Raw conversation data for session details"
            )

            classified_file = st.file_uploader(
                "classified_facets.csv (optional)",
                type=['csv'],
                help="Optional: Classification labels (work/intent)"
            )

            if not (labels_file and assignments_file):
                st.warning("Please upload at least cluster_labels.json and cluster_assignments.csv")
                return

            # Load from uploaded files
            try:
                labels = json.load(labels_file)
                assignments = pd.read_csv(assignments_file)

                raw_sessions = None
                if raw_data_file:
                    raw_df = pd.read_csv(raw_data_file)
                    raw_sessions = {}
                    for session_id, group in raw_df.groupby('session_id'):
                        raw_sessions[session_id] = group.sort_values('update_timestamp').to_dict('records')

                classifications = None
                if classified_file:
                    class_df = pd.read_csv(classified_file)
                    classifications = {}
                    for _, row in class_df.iterrows():
                        key = (str(row['session_id']), str(row.get('facet_idx', 0)))
                        classifications[key] = {
                            'is_work': row.get('is_work', ''),
                            'intent': row.get('intent', '')
                        }

            except Exception as e:
                st.error(f"Error loading files: {e}")
                return
        else:
            # Use default local files
            try:
                labels, assignments = load_cluster_data(DEFAULT_OUTPUT_DIR)
                raw_sessions = load_raw_sessions(RAW_DATA_PATH)
                classifications = load_classifications(CLASSIFIED_DATA_PATH)
            except Exception as e:
                st.error(f"Error loading local data: {e}")
                st.info("Try enabling 'Upload custom data files' to provide your own data.")
                return

        st.success(f"✅ Loaded {len(assignments)} facets")

    # Build hierarchy and ensure classifications are merged into assignments
    leaf_groups, top_groups, parent_map, assignments = build_hierarchy(labels, assignments, classifications)

    # Debug: Check if classifications were applied
    if 'is_work' in assignments.columns:
        classified_count = (assignments['is_work'] != '').sum()
        if classified_count > 0:
            st.sidebar.success(f"✅ {classified_count} facets classified")
        else:
            st.sidebar.warning("⚠️ No classifications found")

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

    # Overall classification stats
    if classifications:
        st.markdown("---")
        all_facets = assignments[assignments['cluster'].astype(str) != '-1'].copy()
        overall_stats = compute_class_stats(all_facets)
        display_classification_badge(overall_stats)

    st.markdown("---")

    # Create tabs for Clusters and Unclustered
    tab1, tab2 = st.tabs(["🗂️ Clusters", "❓ Unclustered"])

    with tab1:
        # Hierarchy navigation
        if top_groups and parent_map:
            # Two-level view
            st.subheader("Cluster Hierarchy")

            # Top-level categories
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

                # Category stats - removed users
                col1, col2 = st.columns(2)
                col1.metric("📊 Sessions", cat_info.get('sessions', 0))
                col2.metric("📈 % of Total", f"{cat_info.get('pct_sessions', 0):.1f}%")

                st.markdown("---")

                # Get child clusters
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

                            # Cluster stats - removed users
                            col1, col2 = st.columns(2)
                            col1.metric("Sessions", child_info.get('sessions', 0))
                            col2.metric("Avg Turns", f"{child_info.get('avg_turns', 0):.1f}")

                            # Show classification stats - ensure cluster ID type matching
                            cluster_facets = assignments[assignments['cluster'].astype(str) == str(child_id)].copy()

                            if classifications and len(cluster_facets) > 0:
                                st.markdown("")
                                stats = compute_class_stats(cluster_facets)
                                display_classification_badge(stats)

                            st.markdown("---")
                            st.markdown("#### 📝 Sample Facets")

                            # Display facets table
                            display_facets_table(cluster_facets, raw_sessions, child_id)

        else:
            # Single-level view
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

                    # Cluster stats - removed users
                    col1, col2 = st.columns(2)
                    col1.metric("Sessions", cluster_info.get('sessions', 0))
                    col2.metric("% of Total", f"{cluster_info.get('pct_sessions', 0):.1f}%")

                    # Show facets - ensure cluster ID type matching
                    cluster_facets = assignments[assignments['cluster'].astype(str) == str(cluster_id)].copy()

                    if classifications and len(cluster_facets) > 0:
                        st.markdown("")
                        stats = compute_class_stats(cluster_facets)
                        display_classification_badge(stats)

                    st.markdown("---")
                    st.markdown("#### 📝 Sample Facets")

                    # Display facets table
                    display_facets_table(cluster_facets, raw_sessions, cluster_id)

    with tab2:
        # Unclustered facets
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

            # Display unclustered facets
            display_facets_table(unclustered, raw_sessions, "unclustered")
        else:
            st.success("All facets were successfully clustered!")


if __name__ == "__main__":
    main()
