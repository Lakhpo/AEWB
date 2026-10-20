"""Independent FABDEM topographic controls, contours, and downloads."""

import json

from branca.element import MacroElement, Template
import folium
import streamlit as st
from shapely.geometry import shape

from geoanalysis.analysis.contours import build_contours
from geoanalysis.analysis.elevation import find_elevation
from geoanalysis.services.elevation import ElevationDataError


class TopographicLegend(MacroElement):
    """A Leaflet legend that follows the dynamic contour layer lifecycle."""

    _template = Template("""
    {% macro script(this, kwargs) %}
    (function() {
    var topoLayer = {{ this._parent.get_name() }};
    var topoLegend = L.control({position: 'bottomleft'});
    topoLegend.onAdd = function() {
        var div = L.DomUtil.create('div');
        div.style.cssText = 'background:white;color:#222;padding:10px 12px;border:1px solid #bbb;border-radius:4px;font:12px/1.6 Arial;box-shadow:0 1px 5px #777;';
        div.innerHTML = '<b>FABDEM topographic map</b><br>' +
            '<span style="display:inline-block;width:28px;border-top:1px solid #8b4513;vertical-align:middle"></span> Contour: {{ this.interval }} m<br>' +
            '<span style="display:inline-block;width:28px;border-top:3px solid #8b4513;vertical-align:middle"></span> Index: {{ this.index_interval }} m<br>' +
            'Elevation: {{ this.low }}&ndash;{{ this.high }} m<br>Datum: EGM2008 &middot; ~30 m grid<br>' +
            '<small>Hawker et al. / Bristol &middot; Copernicus<br>CC BY-NC-SA 4.0 &middot; Not survey contours</small>';
        L.DomEvent.disableClickPropagation(div);
        L.DomEvent.disableScrollPropagation(div);
        return div;
    };
    function addTopoLegend() {
        var target = topoLayer._map;
        if (!target) return;
        if (target._petTopoLegend) target._petTopoLegend.remove();
        topoLegend.addTo(target);
        target._petTopoLegend = topoLegend;
    }
    topoLayer.on('add', addTopoLegend);
    topoLayer.on('remove', function() { topoLegend.remove(); });
    addTopoLegend();
    })();
    {% endmacro %}
    """)

    def __init__(self, contours):
        super().__init__()
        self.interval = f"{contours['interval_m']:g}"
        self.index_interval = f"{contours['index_interval_m']:g}"
        self.low = f"{contours['minimum_m']:.1f}"
        self.high = f"{contours['maximum_m']:.1f}"


def selected_interval():
    value = st.session_state.get("topo_interval", "Auto")
    return None if value == "Auto" else float(value.split()[0])


def prepare_topography(result, collection=None, interval=None):
    """Cache the current geometry/interval on this session's elevation result."""
    key = (json.dumps(collection, sort_keys=True), interval)
    cached = result.get("topography")
    if not cached or cached["key"] != key:
        contours = build_contours(result["geotiff"], collection, interval)
        # Carry source/redistribution metadata into the independent contour file.
        for name in ("source", "source_url", "license", "attribution", "vertical_datum"):
            contours[name] = result["summary"][name]
        cached = {"key": key, "geojson": contours}
        result["topography"] = cached
    return cached["geojson"]


def elevation_overlays(result, visible=True, opacity=0.65, collection=None, interval=None):
    if not result or not visible:
        return []
    try:
        contours = prepare_topography(result, collection, interval)
    except (ElevationDataError, ValueError):
        # The result panel presents the actionable error; keep the map usable.
        return []
    group = folium.FeatureGroup(name="FABDEM topographic contours")
    if contours["features"]:
        folium.GeoJson(contours, pane="terrain", interactive=False,
                       style_function=lambda feature: {"color": "#fff", "opacity": opacity,
                           "weight": 5 if feature["properties"]["index"] else 3}).add_to(group)
        folium.GeoJson(contours, pane="terrain",
                       style_function=lambda feature: {"color": "#8b4513", "opacity": opacity,
                           "weight": 3 if feature["properties"]["index"] else 1.2},
                       tooltip=folium.GeoJsonTooltip(fields=["label"], aliases=["Elevation (EGM2008)"])).add_to(group)
        # Label the longest index segment at each elevation; avoid hundreds of markers.
        labels = {}
        for feature in contours["features"]:
            if feature["properties"]["index"]:
                level = feature["properties"]["elevation_m"]
                line = shape(feature["geometry"])
                if level not in labels or line.length > labels[level].length:
                    labels[level] = line
        for level, line in labels.items():
            point = line.interpolate(0.5, normalized=True)
            folium.Marker([point.y, point.x], interactive=False, pane="terrain",
                icon=folium.DivIcon(icon_size=(54, 18), icon_anchor=(27, 9),
                    html=f'<div style="color:#74380f;background:#ffffffdf;border-radius:3px;text-align:center;font:bold 11px Arial;opacity:{opacity}">{level:g} m</div>')).add_to(group)
    TopographicLegend(contours).add_to(group)
    return [group]


def render_elevation_controls(collection, aoi_key):
    st.divider()
    st.subheader("Terrain elevation · FABDEM")
    st.caption("Ground elevation with forest/building height biases removed, not rooftop surface elevation. "
               "Grid spacing: 1 arc-second (~30 m at the equator). Local AOIs up to 0.1 degrees per axis.")
    st.markdown("[FABDEM V1-2](https://research-information.bris.ac.uk/en/datasets/fabdem-v1-2/) · "
                "[CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/). "
                "Non-commercial use; commercial use requires a separate arrangement with the provider.")
    if st.button("Run FABDEM elevation analysis", use_container_width=True):
        st.session_state.pop("elevation_error", None)
        try:
            with st.spinner("Loading FABDEM terrain and analyzing your AOI…"):
                result = find_elevation(collection)
            result["aoi_key"] = aoi_key
            st.session_state.elevation_result = result
        except (ElevationDataError, ValueError) as error:
            st.session_state.elevation_error = str(error)
        st.rerun()
    st.caption("Initial loading can take a few minutes. Only required tiles are retrieved from Bristol; "
               "your drawings and edits are not uploaded. The analysis stops after three minutes.")
    if st.session_state.get("elevation_error"):
        st.error(st.session_state.elevation_error)
        if st.session_state.get("elevation_result"):
            st.caption("The last successful elevation result is still displayed; the reload failed.")
    result = st.session_state.get("elevation_result")
    if not result or result["aoi_key"] != aoi_key:
        return
    summary = result["summary"]
    stats = summary["statistics"]
    st.checkbox("Show FABDEM elevation", value=True, key="show_elevation")
    st.selectbox("Contour interval", ["Auto", "2 m", "5 m", "10 m", "20 m", "50 m", "100 m"], key="topo_interval")
    st.slider("Contour opacity", 0.0, 1.0, 0.65, step=0.05, key="elevation_opacity")
    contours = None
    try:
        contours = prepare_topography(result, collection, selected_interval())
    except (ElevationDataError, ValueError) as error:
        st.error(f"Topographic map unavailable: {error}")
    st.metric("Minimum terrain elevation", f"{stats['minimum_m']:,.1f} m")
    st.metric("Maximum terrain elevation", f"{stats['maximum_m']:,.1f} m")
    st.caption(f"Mean: {stats['mean_m']:,.1f} m · Median: {stats['median_m']:,.1f} m · "
               f"Relief (max − min): {stats['relief_m']:,.1f} m")
    if contours is not None:
        st.markdown("**Topographic legend**")
        st.caption(f"Thin brown lines: {contours['interval_m']:g} m contours · "
                   f"Heavy labeled lines: {contours['index_interval_m']:g} m index contours. "
                   "Hover a contour for its elevation. The map legend shows the terrain elevation range and datum.")
        st.caption("Contours are interpolated between native FABDEM samples and clipped to the AOI. "
                   "Holes and nodata are not filled; lines may stop short of boundaries. "
                   "A smaller contour interval does not improve the dataset's accuracy.")
        if not contours["features"]:
            st.info("No contour lines cross this AOI at the selected interval. "
                    "Terrain may be flat, the interval too large, or too few adjacent samples available.")
        st.download_button("Download topographic contours GeoJSON", json.dumps(contours, allow_nan=False),
                           file_name="pet-project-fabdem-contours.geojson", mime="application/geo+json",
                           on_click="ignore", use_container_width=True)
    st.caption(f"Valid samples: {stats['valid_pixels']:,} / {stats['selected_pixels']:,} · "
               f"Coverage: {stats['coverage_percent']:.1f}% of selected pixel centers. "
               "Pixel centers define inclusion; AOI holes are excluded. Statistics are unweighted valid-pixel summaries.")
    if stats["nodata_pixels"]:
        st.warning(f"{stats['nodata_pixels']:,} selected pixels have no data. Statistics cover only valid samples, not the entire AOI.")
    st.caption("Elevations are metres relative to EGM2008. This terrain estimate is not an engineering survey; "
               "small features and local slopes may be unresolved. Slope, drainage, and earthwork calculations are not included.")
    st.download_button("Download FABDEM AOI GeoTIFF", result["geotiff"],
                       file_name="pet-project-fabdem-elevation.tif", mime="image/tiff", on_click="ignore",
                       use_container_width=True)
    exported_summary = dict(summary)
    if contours is not None:
        exported_summary["topography"] = {name: contours[name] for name in ("interval_m", "index_interval_m", "method", "notice")}
    st.download_button("Download elevation summary JSON", json.dumps(exported_summary, indent=2, allow_nan=False),
                       file_name="pet-project-fabdem-summary.json", mime="application/json", on_click="ignore",
                       use_container_width=True)
    st.caption("Downloads include source/license metadata. GeoTIFF is native-resolution WGS 84, masked to your AOI; "
               "contour coordinates are WGS 84 and displayed by the map. Results are session-only: download before changing the AOI, refreshing, or restarting.")
    with st.expander("FABDEM attribution"):
        st.write(summary["attribution"])
