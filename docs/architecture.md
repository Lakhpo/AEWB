
# Application architecture

`src/geoanalysis/ui/app.py` is the Streamlit entry point. Folium renders an Esri World Imagery tile layer with attribution and Leaflet.Draw controls. `streamlit-folium` returns `all_drawings` as GeoJSON Features after drawing, editing, and deletion.

The map and AOI confirmation panel run together in a Streamlit fragment so map interactions do not rerun the surrounding page. The component returns its center, zoom, and drawing collection; an on-change callback stores them before rerendering. Center and zoom are passed through the component's dynamic viewport arguments. An empty drawing list clears the selection; a `None` response during initialization does not replace it or reset the saved viewport.

The map script and component key remain stable as selection/viewport data change. Recovery data is serialized separately in the HTML; on an iframe remount, a Folium macro restores the last center/zoom and repopulates the actual editable Leaflet.Draw feature group. It does not add duplicate display-only polygons during normal reruns. The explicit clear button resets the drawings and changes the component key while retaining the current location.

The persistent **Your AOI & GeoJSON** panel sits next to the map. Valid boundaries show a success confirmation, a download button, and an expanded copyable JSON preview. A download is a user-initiated browser file transfer named `pet-project-aoi.geojson`; the application does not automatically write an AOI file to the repository. Selection and viewport recovery are limited to the active Streamlit session, not permanent storage across browser refreshes or server restarts.

Optional Esri World Boundaries and Places and World Transportation reference tile layers supply city labels, administrative boundaries, roads, and street names above satellite imagery, below the AOI drawings. Both are enabled by default and independently exposed in a layer control. Folium's Geocoder control submits address/city/place searches directly from the browser to OpenStreetMap Nominatim. The default result handler fits the result bounds and adds a navigation marker; `zoom=None` preserves that fitted view rather than forcing a city-scale zoom on addresses. The marker is outside Leaflet.Draw's feature group and is not included in `all_drawings` or AOI exports. Suggestions while typing are disabled via the suggestion-length threshold. Search attribution is shown below the map. Public deployment must account for Nominatim's shared rate limit and caching requirements or select another geocoding provider.

`core/geometry.py` validates the entire selection before export: polygon-only geometry, closed rings, finite WGS 84 coordinates, no date-line-crossing edges, and valid topology through Shapely. It returns a fresh FeatureCollection without mutating the component's data. Every drawn polygon is exported; selecting one polygon from several or unioning them is outside this phase.

The UI never exports a stale validated selection after an invalid drawing. It builds the download from the current validated drawings, and disables export by omitting it when validation fails or the selection is empty. Downloading does not trigger an application rerun.

`services/buildings.py` reads the immutable Microsoft GlobalMLBuildingFootprints 2026-08-13 CSV index, decodes quadkeys, and selects candidate source partitions near the AOI bounds (with a 0.002-degree tile-edge lookup margin). It reads gzipped GeoJSONL using temporary files and bounded streaming; no imagery is downloaded. Only the release index is cached in process memory. There is no separate database or AOI upload. `services/imagery.py` remains a placeholder.

`analysis/analysis.py::find_buildings` accepts a GeoJSON AOI FeatureCollection, validates/unions the AOIs, and filters the source geometries for interior overlap. It returns full matching footprints with normalized-geometry deduplication, count, source/release, and processing statistics. Boundary-only touches are excluded. Limits and interrupted/corrupt downloads raise errors rather than publishing partial counts. Invalid source geometry is skipped and reported. Resource limits and coverage limitations are documented in `PROJECT.md`.

Run Analysis is an explicit UI action. A geometry fingerprint binds session results to the selected AOI. AOI changes clear stale results; map navigation retains them. `feature_group_to_add` dynamically supplies a separate orange footprint layer to streamlit-folium, so adding results does not change the map's script identity, replace its viewport, or add buildings to Leaflet.Draw/AOI export. A completed empty result clears the overlay and is explained as a data-coverage result. The UI catches source errors and lets the user retry.

## Building review workspace

`core/building_review.py` supplies source-to-review copies, Polygon editor parts, validation/reassembly, source refresh reconciliation, and separate existing/planned counts. `building_result` remains the original Microsoft response. `building_review` contains active corrected/planned records with Microsoft/manual provenance; `removed_buildings` tracks deleted source IDs. A single `building_undo` snapshot restores the previous accepted review. Invalid drafts never replace validated counts or downloadable data.

The map mode changes which collection is inside Leaflet.Draw: AOI boundaries in AOI mode, working buildings in Buildings mode. The other collection is rendered as a reference overlay. Mode/status changes use a distinct component key and restore the saved viewport; data changes within a mode keep a stable script identity. The recovery macro styles restored buildings by provenance/status and assigns a UUID, provenance, and selected status to newly created building layers before streamlit-folium reads them. New manual features therefore keep IDs across later edit/delete events. Multipart source buildings are split into Polygon parts carrying a common `review_id`, then reassembled in Python for counts/export.

The map callback routes `all_drawings` to AOI handling or building review validation according to the mode. Building edits never overwrite `session_state.drawings` or invalidate the source result. Source refresh merges prior additions/overrides and removed source IDs; changing an AOI explicitly clears the review workspace. New plans do not require source retrieval. All review state is session-only; the separate building GeoJSON download preserves active records with provenance and existing/planned status.

## Provider references

- [Folium drawing controls](https://python-visualization.github.io/folium/latest/user_guide/plugins/draw.html)
- [Folium geocoder](https://python-visualization.github.io/folium/latest/user_guide/plugins/geocoder.html)
- [Nominatim usage policy](https://operations.osmfoundation.org/policies/nominatim/)
- [streamlit-folium](https://github.com/randyzwitch/streamlit-folium)
- [Esri World Imagery](https://www.arcgis.com/home/item.html?id=10df2279f9684e4a9f6a7f08febac2a9)
- [Esri World Transportation service](https://services.arcgisonline.com/ArcGIS/rest/services/Reference/World_Transportation/MapServer)
- [Esri attribution and access guidance](https://doc.arcgis.com/en/arcgis-online/reference/display-copyrights.htm)
- [GlobalMLBuildingFootprints data and license](https://github.com/microsoft/GlobalMLBuildingFootprints)

Public deployment still requires review of provider terms and capacity. No public deployment is performed in Phase 1.

## Current validation

The 24 local tests cover geometry validation, source failures/limits, AOI invalidation, map identity, manual building edits, separate planned counts, multipart identity, undo, and source refresh preservation.

Live source checks on 2026-10-18 used the pinned 2026-08-13 release:

- Madison urban rectangle: west -89.405, south 43.068, east -89.392, north 43.078; 396 matching footprints across two downloaded partitions, with no invalid records skipped.
- Rural Wisconsin rectangle: west -89.505, south 43.195, east -89.48, north 43.215; 65 matching footprints from one downloaded partition, with no invalid records skipped.

These validate the source-to-filter workflow, not the real-world completeness or residential use of the buildings. Automated Streamlit checks verify the count and overlay arguments; visual browser verification of the orange overlays is still required.
