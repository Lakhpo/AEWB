"""Road layer controls, results, and exports for the AOI workspace."""

import html
import json

import folium
import streamlit as st

from geoanalysis.analysis.roads import find_roads
from geoanalysis.services.roads import RoadDataError


def road_overlays(result, show_overture=True, show_osm=True):
    """Keep source centerlines outside the editable AOI/building feature group."""
    if not result:
        return []
    groups = []
    for origin, visible, color, dash in (("overture", show_overture, "#facc15", None),
                                         ("osm", show_osm, "#38bdf8", "6 5")):
        collection = result.get(origin)
        if not visible or not collection or not collection["features"]:
            continue
        label = "OSM" if origin == "osm" else "Overture"
        group = folium.FeatureGroup(name=f"{label} road centerlines")
        # Road names and tags are external text. Escape them before Leaflet
        # renders tooltips, while preserving original values in the download.
        display = {"type": "FeatureCollection", "features": [
            {**feature, "properties": {"name": html.escape(str(feature["properties"]["name"])),
                                       "class": html.escape(str(feature["properties"]["class"])),
                                       "source": label}}
            for feature in collection["features"]
        ]}
        folium.GeoJson(
            display, style_function=lambda feature, color=color, dash=dash:
                {"color": color, "weight": 4, "opacity": 0.85, "dashArray": dash},
            tooltip=folium.GeoJsonTooltip(fields=["name", "class", "source"], aliases=["Road/path", "Class", "Source"]),
        ).add_to(group)
        groups.append(group)
    return groups


def render_road_controls(collection, aoi_key):
    st.divider()
    st.subheader("Streets & roadways")
    include_osm = st.checkbox("Include OSM reference layer", key="roads_include_osm",
                              help="Useful for comparing coverage. It can overlap Overture and is exported separately.")
    if st.button("Load roads", use_container_width=True):
        st.session_state.pop("road_error", None)
        message = st.empty()
        try:
            with st.spinner("Loading road centerlines…"):
                result = find_roads(collection, include_osm=include_osm, progress=message.info)
            result["aoi_key"] = aoi_key
            st.session_state.road_result = result
        except (RoadDataError, ValueError) as error:
            st.session_state.road_error = str(error)
        st.rerun()
    st.caption("Use a neighborhood or local project AOI. Roads load independently of buildings.")
    if st.session_state.get("road_error"):
        st.error(st.session_state.road_error)
        if st.session_state.get("road_result"):
            st.caption("The last successful road result is still displayed; the reload failed.")
    result = st.session_state.get("road_result")
    if not result or result["aoi_key"] != aoi_key:
        return
    st.checkbox("Show Overture roads", value=True, key="show_overture_roads")
    st.metric("Mapped road/path length (Overture)", f"{result['length_m'] / 1000:,.2f} km")
    st.caption(f"{result['count']:,} source segments · release {result['release']}. "
               "Includes footpaths and cycleways; segments are not a count of named streets.")
    if not result["count"]:
        st.warning("No road centerlines matched in this dataset. Coverage may be incomplete.")
    for warning in result["warnings"]:
        st.warning(warning)
    for origin in ("overture", "osm"):
        data = result.get(origin)
        if data is None:
            continue
        if origin == "osm":
            st.checkbox("Show OSM reference roads", value=True, key="show_osm_roads")
            st.caption(f"OSM reference: {len(data['features']):,} ways. Sources overlap; OSM is excluded from the Overture length above.")
        label = "OSM" if origin == "osm" else "Overture"
        st.download_button(f"Download {label} roads GeoJSON", json.dumps(data, indent=2, allow_nan=False),
                           file_name=f"pet-project-{origin}-roads.geojson", mime="application/geo+json",
                           on_click="ignore", use_container_width=True)
    st.caption("Yellow: Overture · Dashed blue: OSM reference. Centerlines are clipped to your AOI. "
               "They do not establish public access or easements. Road results are session-only; download before changing the AOI.")
    st.markdown("Road data: © OpenStreetMap contributors, Overture Maps Foundation · "
                "[ODbL / source attribution](https://docs.overturemaps.org/attribution/)")
