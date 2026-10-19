"""Satellite AOI explorer with Microsoft building counts and footprint overlays.

Run from the repository root with:
    python -m streamlit run src/geoanalysis/ui/app.py
"""

import json
import os
from copy import deepcopy
from pathlib import Path
import sys

from branca.element import MacroElement, Template
import folium
from folium.plugins import Draw, Fullscreen, Geocoder
import streamlit as st
from streamlit_folium import st_folium

# Streamlit watches imported modules under its script directory or PYTHONPATH.
# sys.path alone makes sibling backend modules importable but leaves them
# cached across edits, causing stale imports when new functions are added.
source_root = str(Path(__file__).resolve().parents[2])
sys.path.insert(0, source_root)
python_paths = [path for path in os.environ.get("PYTHONPATH", "").split(os.pathsep) if path]
if source_root not in python_paths:
    os.environ["PYTHONPATH"] = os.pathsep.join([source_root, *python_paths])
from geoanalysis.core.geometry import aoi_feature_collection, parse_coordinates
from geoanalysis.analysis.analysis import find_buildings
from geoanalysis.services.buildings import BuildingDataError
from geoanalysis.core.building_review import (
    editing_parts, merge_analysis, review_counts, source_buildings, validate_building_edits,
)
from geoanalysis.ui.roads import render_road_controls, road_overlays


class RestoreMapState(MacroElement):
    """Recover editable drawings and the viewport if the iframe is remounted.

    Recovery data lives in HTML so changing it does not change the component's
    script hash (which streamlit-folium uses as its widget identity).
    """

    _template = Template("""
        {% macro script(this, kwargs) %}
        var saved = JSON.parse(document.getElementById('aoi-recovery').textContent);
        {{ this._parent.get_name() }}.setView(saved.center, saved.zoom, {animate: false});
        function buildingStyle(feature) {
            var p = feature.properties || {};
            var color = p.status === 'planned' ? '#c084fc' :
                (p.origin === 'manual' ? '#22c55e' : '#ff9f1c');
            return {color: color, fillColor: color, weight: 2, fillOpacity: 0.45};
        }
        L.geoJSON(saved.drawings, saved.editor ? {style: buildingStyle} : {}).eachLayer(function(layer) {
            drawnItems_{{ this.draw.get_name() }}.addLayer(layer);
        });
        {{ this._parent.get_name() }}.on('draw:created', function(e) {
            if (!saved.editor) return;
            var id = 'manual-' + crypto.randomUUID();
            e.layer.feature = {type: 'Feature', id: id, properties: {
                role: 'building', review_id: id, origin: 'manual', status: saved.new_status
            }};
            e.layer.setStyle(buildingStyle(e.layer.feature));
        });
        {% endmacro %}
    """)

    def __init__(self, draw):
        super().__init__()
        self._name = "RestoreMapState"
        self.draw = draw


def build_map(drawings=None, center=None, zoom=4, editor=False, new_status="existing") -> folium.Map:
    """Keep the map script stable; provide recovery data separately."""
    map_view = folium.Map(
        location=[39.5, -98.35], zoom_start=4, tiles=None,
        control_scale=True, max_zoom=19,
    )
    folium.TileLayer(
        tiles="https://services.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        attr=('Tiles &copy; Esri &mdash; Sources: Esri, Maxar, Earthstar Geographics, '
              'and the GIS User Community. '
              '<a href="https://www.arcgis.com/home/item.html?id=10df2279f9684e4a9f6a7f08febac2a9">Imagery credits</a>'),
        name="Satellite imagery", max_zoom=19,
    ).add_to(map_view)
    # Keep navigation labels above imagery and below editable AOI polygons.
    folium.map.CustomPane("navigation_labels", z_index=350, pointer_events=False).add_to(map_view)
    folium.TileLayer(
        tiles="https://services.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}",
        attr="Labels and boundaries &copy; Esri and contributors",
        name="City names and state boundaries", overlay=True, show=True,
        pane="navigation_labels", max_zoom=19,
    ).add_to(map_view)
    folium.TileLayer(
        tiles="https://services.arcgisonline.com/ArcGIS/rest/services/Reference/World_Transportation/MapServer/tile/{z}/{y}/{x}",
        attr="Roads: Esri, HERE, Garmin, &copy; OpenStreetMap contributors",
        name="Street names and roads", overlay=True, show=True,
        pane="navigation_labels", max_zoom=19,
    ).add_to(map_view)
    Geocoder(
        # The default geocoder fits the result's bounds and adds a navigation
        # marker outside Leaflet.Draw's AOI feature group. Preserve that zoom.
        collapsed=False, position="topright", add_marker=True, zoom=None,
        placeholder="Search address or city…",
        error_message="No results. Try a full address with city/state or postal code.",
        # Nominatim permits submitted searches, not autocomplete requests.
        suggest_min_length=1000,
    ).add_to(map_view)
    map_view.get_root().html.add_child(folium.Element(
        '<style>.leaflet-control-geocoder-form input {width: 230px; max-width: 45vw;}</style>'
    ))
    folium.LayerControl(position="bottomright", collapsed=False).add_to(map_view)
    draw = Draw(
        export=False, show_geometry_on_click=False,
        draw_options={
            "polyline": False, "circle": False, "circlemarker": False,
            "marker": False,
            "polygon": {"allowIntersection": False, "showArea": False},
            "rectangle": True,
        },
        edit_options={"edit": True, "remove": True},
    ).add_to(map_view)
    recovery = json.dumps({
        "center": center or [39.5, -98.35], "zoom": zoom,
        "drawings": {"type": "FeatureCollection", "features": drawings or []},
        "editor": editor, "new_status": new_status,
    }).replace("<", "\\u003c")
    map_view.get_root().html.add_child(folium.Element(
        f'<script type="application/json" id="aoi-recovery">{recovery}</script>'
    ))
    RestoreMapState(draw).add_to(map_view)
    Fullscreen().add_to(map_view)
    return map_view


def remember_map_state(result, editor=False):
    """Keep the latest selection and viewport, including explicit deletions."""
    if not result:
        return
    if result.get("all_drawings") is not None:
        if editor:
            remember_building_edits(result["all_drawings"])
        else:
            if selection_key(result["all_drawings"]) != selection_key(st.session_state.get("drawings", [])):
                clear_analysis()
            st.session_state.drawings = result["all_drawings"]
    center = result.get("center")
    if center and center.get("lat") is not None and center.get("lng") is not None:
        st.session_state.map_center = [center["lat"], center["lng"]]
        if result.get("zoom") is not None:
            st.session_state.map_zoom = result["zoom"]


def selection_key(drawings):
    """Bind results to boundary geometry, not the current map viewport."""
    return json.dumps([feature.get("geometry") for feature in drawings], sort_keys=True)


def building_overlay(result):
    """Keep result polygons separate from editable AOI boundaries."""
    if not result or not result["count"]:
        return None
    layer = folium.FeatureGroup(name="Microsoft building footprints")
    folium.GeoJson(
        result["geojson"],
        style_function=lambda feature: footprint_style(feature),
        tooltip="Building footprint (orange: Microsoft, green: manual, purple: planned)",
    ).add_to(layer)
    return layer


def clear_analysis():
    for name in ("building_result", "analysis_error", "building_review", "removed_buildings",
                 "building_edit_error", "building_draft", "last_building_event", "building_undo",
                 "road_result", "road_error"):
        st.session_state.pop(name, None)


def footprint_style(feature):
    props = feature.get("properties", {})
    color = "#c084fc" if props.get("status") == "planned" else (
        "#22c55e" if props.get("origin") == "manual" else "#ff9f1c")
    return {"color": color, "weight": 2, "fillColor": color, "fillOpacity": 0.45}


def remember_building_edits(parts):
    signature = json.dumps(parts, sort_keys=True)
    if signature == st.session_state.get("last_building_event"):
        return
    st.session_state.last_building_event = signature
    originals = st.session_state.get("building_result", {}).get("geojson", {}).get("features", [])
    try:
        reviewed = validate_building_edits(parts, st.session_state.get("drawings", []), originals)
    except ValueError as error:
        st.session_state.building_edit_error = str(error)
        st.session_state.building_draft = parts
        return
    previous = st.session_state.get("building_review", [])
    if reviewed != previous:
        st.session_state.building_undo = (deepcopy(previous), deepcopy(st.session_state.get("removed_buildings", [])))
    st.session_state.building_review = reviewed
    present = {feature["id"] for feature in reviewed}
    st.session_state.removed_buildings = [feature["id"] for feature in source_buildings(originals)
                                         if feature["id"] not in present]
    st.session_state.pop("building_edit_error", None)
    st.session_state.pop("building_draft", None)


def undo_building_edit():
    previous, removed = st.session_state.pop("building_undo")
    st.session_state.building_review = previous
    st.session_state.removed_buildings = removed
    for key in ("building_edit_error", "building_draft", "last_building_event"):
        st.session_state.pop(key, None)
    st.session_state.map_revision = st.session_state.get("map_revision", 0) + 1


def discard_building_draft():
    for key in ("building_edit_error", "building_draft", "last_building_event"):
        st.session_state.pop(key, None)
    st.session_state.map_revision = st.session_state.get("map_revision", 0) + 1


def aoi_overlay(drawings):
    group = folium.FeatureGroup(name="AOI boundary")
    folium.GeoJson({"type": "FeatureCollection", "features": drawings},
                   style_function=lambda feature: {"color": "#3b82f6", "weight": 3, "fillOpacity": 0.03},
                   interactive=False).add_to(group)
    return group


def coordinate_overlay(target):
    """Display a navigation point outside every editable/exported collection."""
    if target is None:
        return None
    group = folium.FeatureGroup(name="Coordinate search location")
    folium.CircleMarker(
        location=target, radius=7, color="white", weight=2,
        fill=True, fill_color="#ef4444", fill_opacity=1,
        tooltip=f"Coordinates: {target[0]:.6f}, {target[1]:.6f}",
    ).add_to(group)
    return group


def render_coordinate_search():
    with st.form("coordinate_search", border=False):
        input_column, button_column = st.columns([3, 1], vertical_alignment="bottom")
        with input_column:
            value = st.text_input(
                "Coordinates (latitude, longitude)", key="coordinate_query",
                placeholder="43.0731, -89.4012",
                help="WGS 84 decimal degrees, latitude first. Negative values indicate south or west.",
            )
        with button_column:
            submitted = st.form_submit_button("Go to coordinates", use_container_width=True)
    if submitted:
        try:
            target = list(parse_coordinates(value))
        except ValueError as error:
            st.session_state.coordinate_error = str(error)
        else:
            st.session_state.map_center = target
            st.session_state.map_zoom = 16
            st.session_state.coordinate_target = target
            st.session_state.pop("coordinate_error", None)
            # A fresh component key prevents its cached previous viewport from
            # overwriting this requested navigation. Recovery restores drawings,
            # the current editor/draft, and the requested center on remount.
            st.session_state.map_revision = st.session_state.get("map_revision", 0) + 1
    if st.session_state.get("coordinate_error"):
        st.error(st.session_state.coordinate_error)
    target = st.session_state.get("coordinate_target")
    if target is not None:
        st.caption(f"Coordinate search location: {target[0]:.6f}, {target[1]:.6f} · Red point on the map.")


@st.fragment
def render_workspace():
    """Update map and confirmation together without rerunning the whole page."""
    render_coordinate_search()
    mode = st.radio("Map tools", ["AOI boundaries", "Buildings"], horizontal=True, key="map_mode",
                    disabled=not st.session_state.get("drawings"))
    editor = mode == "Buildings"
    new_status = "existing"
    if editor:
        kind = st.radio("New footprints represent", ["Existing building", "Planned building"], horizontal=True)
        new_status = "planned" if kind == "Planned building" else "existing"
        st.info("Draw a missing or planned building with the polygon/rectangle tool. "
                "Use the trash tool to remove false positives, or the edit tool to adjust footprints; click Save when finished. "
                "The blue AOI boundary is locked in this mode.")
    else:
        st.caption("Switch Map tools to Buildings to correct footprints or draw plans. "
                   "Changing the AOI clears the building review; download your edited buildings first.")
    if "building_review" not in st.session_state:
        originals = st.session_state.get("building_result", {}).get("geojson", {}).get("features", [])
        st.session_state.building_review = source_buildings(originals)
    map_column, selection_column = st.columns([3, 1])
    key = f"aoi_map_{st.session_state.get('map_revision', 0)}_{mode}_{new_status}"

    def on_map_change():
        remember_map_state(st.session_state.get(key), editor=editor)

    with map_column:
        reviewed = st.session_state.get("building_review", [])
        editable = st.session_state.get("building_draft", editing_parts(reviewed)) if editor else st.session_state.get("drawings", [])
        overlay = aoi_overlay(st.session_state.get("drawings", [])) if editor else building_overlay({
            "count": len(reviewed), "geojson": {"type": "FeatureCollection", "features": reviewed},
        })
        overlays = ([overlay] if overlay else []) + road_overlays(
            st.session_state.get("road_result"),
            show_overture=st.session_state.get("show_overture_roads", True),
            show_osm=st.session_state.get("show_osm_roads", True),
        )
        target_overlay = coordinate_overlay(st.session_state.get("coordinate_target"))
        if target_overlay is not None:
            overlays.append(target_overlay)
        result = st_folium(
            build_map(editable,
                      st.session_state.get("map_center"),
                      st.session_state.get("map_zoom", 4), editor=editor, new_status=new_status),
            key=key, height=600, use_container_width=True,
            center=st.session_state.get("map_center"),
            zoom=st.session_state.get("map_zoom"),
            returned_objects=["all_drawings", "center", "zoom"],
            on_change=on_map_change,
            feature_group_to_add=overlays or None,
        )
        remember_map_state(result, editor=editor)

    with selection_column:
        st.subheader("Your AOI & GeoJSON")
        drawings = st.session_state.get("drawings", [])
        if not drawings:
            st.info("Draw a polygon or rectangle to select your AOI.")
            st.caption("Your download and coordinate preview will appear here.")
            st.button("Run Analysis", disabled=True)
            return
        try:
            collection = aoi_feature_collection(drawings)
        except ValueError as error:
            st.error(f"Cannot export this selection: {error} Edit or delete the invalid boundary.")
            return
        st.success(f"AOI selected successfully! {len(collection['features'])} boundary/boundaries ready.")
        st.write("Your selection stays available while you navigate or edit the map.")
        if st.button("Run Analysis", type="primary", use_container_width=True):
            message = st.empty()
            st.session_state.pop("analysis_error", None)
            try:
                with st.spinner("Loading Microsoft building footprints…"):
                    result = find_buildings(collection, progress=message.info)
                result["aoi_key"] = selection_key(drawings)
                st.session_state.building_review = merge_analysis(
                    result["geojson"]["features"], st.session_state.get("building_review", []),
                    st.session_state.get("removed_buildings", []),
                )
                st.session_state.building_result = result
                for name in ("building_edit_error", "building_draft", "last_building_event", "building_undo"):
                    st.session_state.pop(name, None)
                st.session_state.map_revision = st.session_state.get("map_revision", 0) + 1
            except (BuildingDataError, ValueError) as error:
                st.session_state.analysis_error = str(error)
            st.rerun()
        st.caption("Counts building footprints, including non-residential buildings. "
                   "Start with a neighborhood-sized AOI. Source files can take a few minutes to read.")
        if st.session_state.get("analysis_error"):
            st.error(st.session_state.analysis_error)
        reviewed = st.session_state.get("building_review", [])
        edit_error = st.session_state.get("building_edit_error")
        if edit_error:
            st.error(f"Building edits not saved: {edit_error} Counts show the last valid review.")
            st.button("Discard unsaved building edits", on_click=discard_building_draft)
        if st.session_state.get("building_undo") is not None:
            st.button("Undo last building edit", on_click=undo_building_edit, use_container_width=True)
        if reviewed or editor or st.session_state.get("building_result"):
            counts = review_counts(reviewed)
            st.metric("Existing buildings (review)", counts["existing"])
            st.metric("Planned buildings", counts["planned"])
            st.caption("Orange: Microsoft · Green: manually added · Purple: planned. "
                       "Planned buildings are excluded from the existing-building count.")
            st.download_button(
                "Download edited buildings GeoJSON",
                json.dumps({"type": "FeatureCollection", "features": reviewed,
                            "source": "Microsoft GlobalMLBuildingFootprints and user edits",
                            "source_release": st.session_state.get("building_result", {}).get("release"),
                            "license": "https://cdla.dev/permissive-2-0/"}, indent=2, allow_nan=False),
                file_name="pet-project-buildings.geojson", mime="application/geo+json",
                on_click="ignore", disabled=bool(edit_error), use_container_width=True,
            )
            st.caption("Edits are session-only. Download before refreshing or changing the AOI. "
                       "Source refreshes retain valid manual additions, edits, and removals for this AOI.")
        result = st.session_state.get("building_result")
        if result and result["aoi_key"] == selection_key(drawings):
            st.caption(f"Original Microsoft matches: {result['count']} · "
                       f"Removed source buildings: {len(st.session_state.get('removed_buildings', []))}")
            if result["count"]:
                st.caption("The review includes source buildings plus your corrections. "
                           "Buildings crossing the AOI boundary are counted once.")
            else:
                st.warning("No footprints matched in the available dataset. This does not prove there are no buildings here.")
            st.caption(f"Microsoft GlobalMLBuildingFootprints · release {result['release']} · "
                       "[CDLA Permissive 2.0](https://cdla.dev/permissive-2-0/). "
                       "Coverage and imagery dates vary; this is not a verified house count.")
            if result["skipped"]:
                st.warning(f"{result['skipped']} invalid source records were skipped; the count may be incomplete.")
        elif reviewed or editor:
            st.caption("Microsoft analysis has not been run for this AOI. You can draw buildings and plans now; "
                       "these counts describe your review, not a complete inventory.")
        st.download_button(
            "Download AOI GeoJSON", json.dumps(collection, indent=2, allow_nan=False),
            file_name="pet-project-aoi.geojson", mime="application/geo+json",
            on_click="ignore", use_container_width=True,
        )
        st.caption("Saves pet-project-aoi.geojson to your browser's download location "
                   "(usually Downloads). No file is saved until you click Download.")
        render_road_controls(collection, selection_key(drawings))
        with st.expander("View / copy GeoJSON", expanded=True):
            st.caption("WGS 84 · [longitude, latitude]. Use the code block's copy button.")
            st.code(json.dumps(collection, indent=2, allow_nan=False), language="json")


def main() -> None:
    st.set_page_config(page_title="Pet Project | AOI Explorer", page_icon="🌍", layout="wide")
    st.title("Pet Project")
    st.caption("Explore satellite imagery · Select an area of interest · Export your boundary")
    with st.sidebar:
        st.header("Select your AOI")
        st.markdown(
            "1. Search for an address or city in the map's upper-right box and press Enter, or zoom and pan.\n"
            "2. Choose the polygon or rectangle tool on the map.\n"
            "3. Draw your boundary; click the first vertex to finish a polygon.\n"
            "4. Use the edit or trash tool, then **Save**, to change your selection."
        )
        st.caption("You can draw multiple boundaries. The download includes every valid drawn shape.")
        st.caption("City names, state boundaries, and streets are on by default. "
                   "Zoom in for street names. Toggle layers in the map's lower-right control.")
        st.caption("For addresses, include the house number, street, city, and state or postal code. "
                   "The search pin marks a location; draw a boundary to create an AOI.")
        if st.button("Clear AOI and building edits", use_container_width=True):
            st.session_state.map_revision = st.session_state.get("map_revision", 0) + 1
            st.session_state.drawings = []
            clear_analysis()
            st.session_state.map_mode = "AOI boundaries"
        st.divider()
        st.markdown("**Building data**")
        st.markdown("[Microsoft GlobalMLBuildingFootprints](https://github.com/microsoft/GlobalMLBuildingFootprints)")
        st.caption("Draw an AOI, then click Run Analysis to count and display available building footprints.")

    render_workspace()
    st.caption("Imagery requires an internet connection; image dates and detail vary by location. "
               "If tiles appear blank, check your connection or zoom out.")
    st.caption("Address and city search: © OpenStreetMap contributors, via Nominatim. "
               "Searches are sent to OpenStreetMap when you press Enter. "
               "Address coverage varies; include a city, state, or country to narrow the results.")


if __name__ == "__main__":
    main()
