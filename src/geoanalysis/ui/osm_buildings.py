"""Independent OSM building controls and read-only footprint overlay."""

import json

import folium
import streamlit as st

from geoanalysis.analysis.osm_buildings import find_osm_buildings
from geoanalysis.services.buildings import BuildingDataError


def osm_building_overlays(result, visible=True):
    if not result or not visible or not result["count"]:
        return []
    group = folium.FeatureGroup(name="OSM building footprints")
    # No untrusted source tags are interpolated into HTML tooltips.
    folium.GeoJson(result["geojson"],
                   style_function=lambda feature: {"color": "#06b6d4", "weight": 2, "fillOpacity": 0.3},
                   tooltip="OSM building footprint (reference)").add_to(group)
    return [group]


def render_osm_building_controls(collection, aoi_key):
    st.divider()
    st.subheader("OSM building footprints")
    st.caption("Compare OSM with Microsoft to investigate missing footprints. "
               "OSM is a separate, read-only layer; overlapping sources are not added to the review count.")
    if st.button("Load OSM buildings", use_container_width=True):
        st.session_state.pop("osm_building_error", None)
        try:
            with st.spinner("Loading OSM building footprints…"):
                result = find_osm_buildings(collection)
            result["aoi_key"] = aoi_key
            st.session_state.osm_building_result = result
        except (BuildingDataError, ValueError) as error:
            st.session_state.osm_building_error = str(error)
        st.rerun()
    st.caption("Queries your AOI bounds via Overpass. Limit: 0.1 degrees per axis. "
               "Works without running Microsoft analysis.")
    if st.session_state.get("osm_building_error"):
        st.error(st.session_state.osm_building_error)
        if st.session_state.get("osm_building_result"):
            st.caption("The last successful OSM building result is still displayed; the reload failed.")
    result = st.session_state.get("osm_building_result")
    if not result or result["aoi_key"] != aoi_key:
        return
    st.checkbox("Show OSM buildings", value=True, key="show_osm_buildings")
    st.metric("OSM building footprints (separate)", result["count"])
    if not result["count"]:
        st.warning("No OSM building footprints matched. This does not prove there are no buildings here.")
    st.caption("Cyan: OSM. Full footprints overlapping the AOI interior count once; boundary-only touches do not. "
               "Coverage varies in rural and urban areas. Point buildings and building:part-only records are excluded. "
               "Bounding-box queries can miss crossing buildings without a node inside the query bounds.")
    st.download_button("Download OSM buildings GeoJSON", json.dumps(result["geojson"], indent=2, allow_nan=False),
                       file_name="pet-project-osm-buildings.geojson", mime="application/geo+json",
                       on_click="ignore", use_container_width=True)
    st.markdown("Building data: © OpenStreetMap contributors · [ODbL](https://www.openstreetmap.org/copyright)")
    st.caption("OSM data is session-only. Download before refreshing, restarting, or changing the AOI. "
               "OSM downloads retain source IDs, tags, query time, and license; review and AOI downloads stay separate.")
