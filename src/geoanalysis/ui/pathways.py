"""Session-only pathway review state, controls, and reference overlays."""

from copy import deepcopy
import json

import folium
import streamlit as st

from geoanalysis.core.pathways import pathway_collection, validate_pathways


def remember_pathway_edits(features):
    signature = json.dumps(features, sort_keys=True)
    if signature == st.session_state.get("last_pathway_event"):
        return
    st.session_state.last_pathway_event = signature
    try:
        reviewed = validate_pathways(features, st.session_state.get("drawings", []))
    except ValueError as error:
        st.session_state.pathway_edit_error = str(error)
        st.session_state.pathway_draft = features
        return
    previous = st.session_state.get("pathway_review", [])
    if previous != reviewed:
        st.session_state.pathway_undo = deepcopy(previous)
    st.session_state.pathway_review = reviewed
    for name in ("pathway_draft", "pathway_edit_error"):
        st.session_state.pop(name, None)


def discard_pathway_draft():
    for name in ("pathway_draft", "pathway_edit_error", "last_pathway_event"):
        st.session_state.pop(name, None)
    st.session_state.map_revision = st.session_state.get("map_revision", 0) + 1


def undo_pathway_edit():
    st.session_state.pathway_review = st.session_state.pop("pathway_undo")
    discard_pathway_draft()


def pathway_style(feature):
    return {"color": "#f472b6", "weight": 4,
            "dashArray": "7 5" if feature.get("properties", {}).get("status") == "planned" else None}


def pathway_overlays(features):
    if not features:
        return []
    group = folium.FeatureGroup(name="User pathway sketches (access unverified)")
    folium.GeoJson(pathway_collection(features), style_function=pathway_style,
                   tooltip="User pathway sketch · public access unverified").add_to(group)
    return [group]


def render_pathway_controls(editor=False):
    features = st.session_state.get("pathway_review", [])
    if not editor and not features and not st.session_state.get("pathway_edit_error"):
        return
    st.divider()
    st.subheader("Pathway sketches")
    error = st.session_state.get("pathway_edit_error")
    if error:
        st.error(f"Pathway edits not saved: {error} Totals show the last valid sketches.")
        st.button("Discard unsaved pathway edits", on_click=discard_pathway_draft)
    if "pathway_undo" in st.session_state:
        st.button("Undo last pathway edit", on_click=undo_pathway_edit, use_container_width=True)
    existing = [f for f in features if f["properties"]["status"] == "existing"]
    planned = [f for f in features if f["properties"]["status"] == "planned"]
    st.caption(f"User-mapped existing paths: {len(existing)} · Planned paths: {len(planned)}")
    st.caption(f"Existing sketch length: {sum(f['properties']['length_m'] for f in existing):,.1f} m · "
               f"Planned sketch length: {sum(f['properties']['length_m'] for f in planned):,.1f} m. "
               "Lengths are geodesic estimates; crossing/overlapping sketches are not merged.")
    st.download_button("Download pathway sketches GeoJSON",
                       json.dumps(pathway_collection(features), indent=2, allow_nan=False),
                       file_name="pet-project-pathways.geojson", mime="application/geo+json",
                       on_click="ignore", disabled=bool(error), use_container_width=True)
    st.caption("Pink solid: user-mapped existing · Pink dashed: planned. Public access is unverified. "
               "Road sources remain separate references. Sketches are session-only: download before "
               "refreshing, restarting, or changing/clearing the AOI.")
