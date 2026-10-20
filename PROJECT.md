# Pet Project

## Vision and current scope

Pet Project is a Python-based geospatial web application intended for public access through a shareable URL. Users will select geographic regions on satellite imagery and run automated geospatial analysis without installing Python locally.

The initial analytical objective is to identify and count buildings within user-selected Areas of Interest (AOIs), including rural areas. Prefer established building footprint datasets before developing custom roof-detection models.

The current checkpoint covers the AOI-to-building workflow across Phases 2–4: Microsoft footprint retrieval, counting, overlays, downloads, and manual building review/planning, plus independent Overture road centerlines and optional OSM reference roads within the AOI. The authorized pathway increment adds manual line sketches, extension/editing, removal, undo, and separate export. Source-road editing, automatic routing/snapping, easements, further engineering analysis, custom models, architecture migrations, and deployment remain deferred.

The authorized building-source increment adds an independent optional OSM building footprint layer to compare coverage gaps, with separate counts and GeoJSON downloads. Microsoft analysis and editable reviews remain unchanged. Automatic cross-source matching/merging and OSM-to-review import are deferred.

The authorized elevation increment adds FABDEM V1-2 terrain statistics, an AOI-masked topographic contour overlay with legend, and GeoTIFF/contour/summary downloads. This is ground-terrain analysis, not rooftop surface modeling. Slope, hydrology, earthworks, and other engineering calculations remain deferred.

## Intended user experience

1. Visit a shareable application link and see an interactive satellite map of Earth.
2. Zoom and pan to a location, then draw a polygon or rectangle to define an AOI.
3. Convert the selected boundary into geographic coordinates and GeoJSON.
4. Click **Run Analysis** to execute Python backend functions for that AOI.
5. View analysis results on the map and, in a later phase, download results.

## Requirements and design principles

- Keep the web interface, boundary handling, data access, and analysis modular.
- Prioritize open-source tools and low-cost services suitable for eventual public deployment.
- Support rural and urban regions; document dataset coverage and limitations rather than assuming complete coverage.
- Use GeoJSON for AOI interchange. Geographic GeoJSON coordinates use longitude, latitude order in WGS 84; explicitly handle coordinate reference systems for later geospatial operations.
- Keep code readable, documented, and maintainable, with validation appropriate to each phase.
- Use Esri World Imagery tiles for the initial interactive map, with visible attribution and a link to imagery credits. Review provider access terms and hosting costs before public deployment; map display does not authorize bulk imagery downloads.
- Microsoft [GlobalMLBuildingFootprints](https://github.com/microsoft/GlobalMLBuildingFootprints) supplies existing model-derived footprints to filter/count within an AOI, not live detection on the displayed map or residential classification. The first integration uses the immutable 2026-08-13 index/release under CDLA Permissive 2.0. Coverage, freshness, and rural accuracy vary; displayed imagery can differ from source imagery.

## Proposed technology stack

| Component | Initial choice / intended role |
| --- | --- |
| Application and backend | Python |
| Web interface | Streamlit |
| Interactive map and drawing | Folium and streamlit-folium |
| AOI boundary interchange | GeoJSON |
| Geospatial processing | Shapely, pyproj, Rasterio, NumPy; GeoPandas remains deferred |
| Initial hosting candidate | Streamlit Community Cloud |
| Potential later architecture | FastAPI, separate frontend, and background workers |

Runtime dependencies are recorded in `requirements.txt`: Streamlit, Folium, streamlit-folium, Shapely for geometry validation, requests for source downloads, overturemaps for road retrieval, pyproj for geodesic length measurements, Rasterio/NumPy for terrain rasters, Pillow for worker previews, and ContourPy for topographic isolines. GeoPandas remains deferred. Deployment compatibility will be validated before hosting.

## Proposed architecture and repository structure

Retain the existing `src/geoanalysis` package and directories. Pet Project is the application name; no package rename or new `backend` directory is needed. The proposed runtime flow is: Streamlit UI -> AOI validation and normalization -> analysis functions -> data services as needed -> map overlays and downloads.

```text
PROJECT.md                          # Scope, requirements, architecture, and roadmap
AGENTS.md                           # Durable development instructions
README.md                           # User-facing overview and eventual run instructions
requirements.txt                    # Runtime dependencies as phases require them
src/
  geoanalysis/
    __init__.py                     # Existing Python package
    ui/
      app.py                        # Streamlit map, drawing controls, and results
      roads.py                      # Independent road controls, overlays, and downloads
      osm_buildings.py              # Independent OSM building reference layer
      pathways.py                   # User pathway sketch controls and overlays
      elevation.py                  # FABDEM terrain controls and raster overlay
    core/
      geometry.py                   # AOI validation, coordinates, GeoJSON, CRS handling
      building_review.py            # Manual review, planning status, and source reconciliation
      pathways.py                   # Pathway validation and geodesic sketch measurements
    services/
      imagery.py                    # Imagery access/downloads when required
      buildings.py                  # Microsoft partition index and bounded GeoJSONL reads
      roads.py                      # Bounded Overture worker and OSM highway queries
      osm_buildings.py              # Bounded Overpass building/multipolygon access
      elevation.py                  # Bounded official FABDEM archive range access
    analysis/
      analysis.py                   # AOI-driven processing and building analysis
      roads.py                      # AOI clipping and per-source geodesic road measurements
      osm_buildings.py              # Independent OSM footprint selection/counting
      elevation.py                  # Native-grid terrain statistics, masking, and exports
tests/                              # Phase-appropriate validation
data/
  samples/                          # Small, redistributable sample inputs only
docs/
  architecture.md                   # Detailed design decisions when needed
notebooks/                          # Exploratory work, outside the production path
scripts/                            # Development and maintenance utilities
.github/
  workflows/
    ci.yml                          # Automated checks when implemented
```

This structure reflects existing directories. UI modules implement map/AOI, building review, and road controls; core modules validate/reconcile edits; services supply Microsoft footprints and Overture/OSM roads; analysis modules filter, clip, count, and measure them. The imagery-download module remains a placeholder. Keep Streamlit-specific state and widgets in `ui`; backend modules accept ordinary Python/geospatial inputs without depending on Streamlit. Map tile display and imagery downloads are separate needs; this workflow does not implement imagery downloads.

## Development roadmap and phase validation

### Phase 1 — Interactive map

Build a browser-based Streamlit application with satellite imagery, zooming, panning, and polygon/rectangle drawing. Capture AOI coordinates and allow GeoJSON export.

Navigation includes enabled-by-default Esri World Boundaries and Places and World Transportation reference overlays for city names, administrative boundaries, roads, and street names, with independent layer toggles. Submitted address/city/place search through Folium's Nominatim geocoder fits the result's bounds and displays a location pin while preserving drawn AOIs. The pin does not create an AOI and is excluded from exports. Street labels depend on zoom and address results depend on dataset coverage. Autocomplete is disabled. Review Nominatim's usage policy before public deployment and use a provider suitable for expected traffic.

Validate map display, both drawing tools, coordinate order, and successful export of a valid selected boundary. Handle missing or invalid selections clearly. Provider choice and required attribution belong to this phase; building analysis belongs to subsequent phases.

Coordinate navigation accepts WGS 84 decimal degrees in **latitude, longitude** order above the map, separated by a comma or whitespace. Validate finite values and latitude/longitude bounds before navigating. **Go to coordinates** zooms to the target and displays a red reference point while retaining AOIs, manual building work, and road results. The point does not enter any GeoJSON export. Navigation works without an AOI and makes no geocoding request. Degrees/minutes/seconds input is deferred.

Completing or editing an AOI must retain the current map location/zoom and show persistent selection confirmation. Present the GeoJSON download and copyable preview next to the map, with the filename and browser download destination explained. Preserve the editable selection and viewport through reruns within the active session; permanent AOI storage is outside Phase 1.

### Phase 2 — Python backend integration

Connect a **Run Analysis** action to modular Python functions accepting the selected AOI. Define input/output contracts and surface progress and errors in the UI.

Validate that the selected AOI reaches a backend function and its output returns to the interface. The authorized initial integration connects directly to the Phase 3 footprint workflow below.

### Phase 3 — Building identification

Investigate existing global building footprint datasets and their licensing, coverage, freshness, and rural performance. Implement building identification and counting within selected AOIs. Explore computer vision roof detection only where existing datasets are insufficient and after the approach is requested and agreed.

Validate representative rural and urban AOIs. Define boundary inclusion/counting rules and explain missing coverage and uncertainty.

### Phase 4 — Results visualization

Overlay identified footprints on the map, present building counts, and provide downloadable results.

Validate overlay alignment, consistency between displayed and exported counts, and usable geospatial downloads.

### Current analysis contract

`find_buildings(collection, progress=None)` accepts the validated AOI FeatureCollection and returns a footprint FeatureCollection, matching count, Microsoft source/release, and processing metadata. Source results remain separate from editable reviews and AOI exports.

Microsoft publishes a geographic index and gzipped GeoJSONL files, not a SQL/AOI endpoint. Python selects relevant quadkey partitions, downloads them to temporary files, filters locally, and deletes the temporary files. The boundary itself is not uploaded. The immutable index is cached in process memory; building results remain session-only.

Count each unique full footprint with interior overlap with any selected AOI once. Union AOIs and deduplicate normalized geometry; footprints that merely touch an AOI edge/point do not count. Include a 0.002-degree search margin around the AOI bounds when selecting source tiles to reduce tile-edge omissions. This margin is not a completeness guarantee; incomplete source coverage, very large boundary-crossing structures, missing/invalid records, and differing imagery dates can affect counts. Counts do not establish residential use or occupancy.

Prototype limits: AOI bounding-box spans at most 0.5 degrees per axis, at most four source partitions, 100 MiB total compressed download, 1 GiB decompressed data, 180 seconds for file download/scanning (plus initial index retrieval), and 10,000 matched footprints. Limit/network/corruption failures return errors without partial counts. No matching partitions is a coverage error; a completed zero-match query is explicitly described as a dataset result, not proof of no buildings. Changing/deleting an AOI clears prior results; panning does not. The first implementation uses no separate database, worker service, or custom detection model.

### Manual review and project planning

The map has separate **AOI boundaries** and **Buildings** modes. In Buildings mode, existing source/manual footprints are editable/deletable and the AOI is a locked reference outline. New polygons/rectangles can represent an existing building (missing from the source) or a planned building. Plans can be drawn before running source analysis. Orange identifies Microsoft footprints, green manual additions, and purple planned buildings. Existing and planned counts are displayed separately; plans never increase the existing-building count.

Manual edits must be valid polygons and each building must overlap the AOI interior. Reject invalid/outside/duplicate same-status footprints as a whole edit snapshot, retain the last valid count, disable review download while the draft is invalid, and allow draft discard. Multipart source buildings are decomposed into editable Polygon layers and reassembled under their stable parent ID, so parts still count as one building. Removing all parts removes the building. Offer a single-step undo for accepted building edits.

The source result is immutable in session state. The working review tracks stable source IDs, geometry adjustments, manually added records, existing/planned status, and removed source IDs. Running analysis again for the same AOI preserves valid corrections, plans, and removals. Changing/clearing the AOI resets the building workspace; the UI instructs users to download first. `pet-project-buildings.geojson` exports active building records and provenance/license metadata. Edited reviews remain session-only; project re-import is not implemented.

### Optional OSM building footprints

`analysis/osm_buildings.py::find_osm_buildings(collection)` validates/unions the AOI, queries worldwide AOI bounds through Overpass, and returns a separate footprint FeatureCollection and count. `services/osm_buildings.py` retrieves full geometry for `building` ways and building multipolygon relations, reconstructs split/reversed outer and inner member ways, preserves courtyards/multipart footprints, and excludes member ways already represented by a relation. Count unique full footprints with AOI interior overlap once; exclude boundary-only touches. Retain stable OSM IDs, original tags, ODbL license, attribution, retrieval time, and source timestamp. Points, `building=no`, and building-part-only features are excluded.

`ui/osm_buildings.py` supplies explicit **Load OSM buildings**, a cyan read-only overlay, visibility toggle, separate count, and separate download. It works without Microsoft analysis, preserves the Microsoft original/review and roads/viewport, and never places OSM features in editable groups. Do not add source counts together or claim they describe unique combined buildings. AOI changes clear OSM results/errors; failed reloads retain the last successful result with an explicit notice. All results are session-only.

OSM building AOIs span at most 0.1 degrees per axis. Overpass requests use a 40-second server timeout, 10-second connect/50-second read timeouts, a 60-second streaming check, 20 MiB response cap, and at most 10,000 returned records. Invalid geometry, partial-query remarks, network errors, and limits return actionable errors without partial/false-zero results. No API key is required; explicit loading sends AOI bounds to Overpass. OSM coverage varies in urban/rural areas and bbox queries can miss crossing buildings without a node in bounds. Respect ODbL attribution and applicable redistribution/share-alike requirements.

Validate courtyard/multipart reconstruction, relation/member deduplication, full-footprint interior overlap, holes/touches, worldwide bounds, failure/limit handling, source isolation, AOI invalidation, and unchanged viewport/review/roads. Exercise rural/urban live queries and manually inspect map rendering when browser access is available.

### Streets and roadways increment

Use **Load roads** independently of **Run Analysis**. Query the AOI bounds worldwide with Overture's official Python client (1.0.2), pinned transportation release **2026-09-23.1**, selecting subtype `road`. This includes streets, tracks, footpaths, and cycleways, with rail/water excluded. Preserve Microsoft building analysis and manual review unchanged.

Validate/union AOIs, clip road lines to their interiors (excluding holes and boundary-only contacts), retain stable source IDs and attributes, and calculate WGS 84 geodesic centerline lengths. Source access rules retain their original segment/way scope and fractions; do not treat them as verified public access or easement boundaries. Query location comes directly from the AOI; no country selector or reverse geocoder is needed.

Optionally retrieve live OSM highway ways with Overpass as a separate reference layer. Overture already incorporates OSM, so preserve separate layers, source counts, and downloads rather than adding overlapping lengths together. Yellow lines identify Overture; dashed blue lines identify OSM. The displayed length covers Overture only and includes road-subtype paths. Segment counts are not counts of named roads. GeoJSON exports retain original source attributes and ODbL attribution. Results remain session-only and are invalidated when the AOI changes.

Road AOI bounds may span at most **0.1 degrees per axis**. Overture runs in a subprocess with a **180-second hard timeout**, at most **30,000 scanned records**, **10,000 road records**, and **20 MiB JSON output**. OSM responses are bounded to **20 MiB**, **10,000 ways**, a **40-second query timeout**, network timeouts, and a 60-second streaming check. Primary failures never publish partial or false-zero results; a failed reload explicitly retains the last successful road result. Optional OSM failures display a warning while preserving Overture roads. Source coverage and positional accuracy vary; OSM bbox queries may miss crossing ways without a node in the query bounds.

Validate clipping, holes, source failures/limits, source separation, worldwide bounds, overlay identity, AOI invalidation, and preservation of building edits/viewport. Exercise a live source query and manually check browser rendering when a browser is available. Road editing, automatic source conflation, routing, corridor planning, and public-easement lookup are outside this increment.

### Manual pathway sketches

**Pathways** map mode lets users draw line sketches, extend their own lines by moving endpoints, add bends with midpoint handles, and edit/delete with Save. New sketches default to planned, with an optional user-mapped existing status. Existing mapped road/path sources remain independent locked references; users can draw connecting sketches without importing or modifying source records. There is no automatic snapping, routing, or verification of public access/easements. Pink dashed lines identify planned sketches; pink solid lines identify user-mapped existing paths. Every sketch/export explicitly records `public_access=unverified`.

`core/pathways.py` validates a whole LineString snapshot before accepting it. Require finite WGS 84 longitude/latitude coordinates, 2–2,000 vertices per line, no consecutive duplicate vertices, no date-line crossings or self-crossings, unique IDs/geometries (including reversed lines), and at most 1,000 sketches. Lines must stay inside the unioned AOI and outside its holes with some line interior inside the AOI; endpoints may meet the boundary. Invalid drafts preserve accepted sketches/totals and disable pathway export until corrected/discarded. Geodesic WGS 84 lengths use pyproj, with separate existing/planned sketch totals; overlapping routes are not conflated.

`ui/pathways.py` maintains independent session review/draft/undo state and separate GeoJSON download. A single-step undo restores the previous accepted pathway snapshot, including deletions. Map navigation, coordinate search, mode changes, and source refreshes retain pathways and viewport. AOI changes/clear invalidate pathway work alongside other AOI-bound results. AOI/building edits and source downloads exclude pathways; only `pet-project-pathways.geojson` exports sketches. Download before refreshing/restarting/changing the AOI; persistence/re-import is deferred.

Validate add/extend/delete/undo, invalid-draft recovery and disabled export, reversed duplicates, holes/boundaries, geodesic lengths, stable IDs and map identity, mode switches, AOI invalidation, and preservation of source/building work. Manually check line drawing and endpoint/midpoint editing when browser access is available.

### FABDEM terrain elevation

**Run FABDEM elevation analysis** operates independently of building, pathway, and road workflows. Use official University of Bristol FABDEM V1-2: a ground-elevation estimate with forest/building height biases removed, at 1 arc-second grid spacing (~30 m at the equator), horizontal WGS 84 and vertical EGM2008. Source license is **CC BY-NC-SA 4.0**, not unrestricted commercial/open use; the UI and exports disclose non-commercial/share-alike terms and source attribution, including required Copernicus credit/disclaimer. Commercial use requires separate arrangements with the provider; public deployment remains deferred.

`services/elevation.py` resolves worldwide 1-degree tile names and enclosing 10-degree archives. It uses validated HTTP byte ranges and Python ZIP access to retrieve required members without downloading full regional archives. A half-cell lookup margin covers point-registered tile edges; missing archives/members are coverage errors, never zero elevations. Do not silently substitute another DEM. Shared transfer limit: 256 MiB, at most four tiles, 80 MiB compressed/expanded per tile, 10-second connect/30-second read timeouts, and time checks. Raw rasters and bulk archives are not retained in the repository.

`analysis/elevation.py::find_elevation(collection)` validates/combines AOIs before starting a worker with a 180-second hard timeout. AOIs may span at most 0.1 degrees per axis and must lie between 85°S and 85°N for this map display. Rasterio validates CRS/layout/resolution, crops native-grid windows, mosaics tile seams, masks to AOI pixel centers (excluding holes), and limits the mosaic to 200,000 pixels. Summaries include minimum, maximum, mean, median, standard deviation, 5th/95th percentiles, relief, valid/selected/nodata samples, and coverage percentage. Statistics are unweighted valid-pixel summaries, not area-weighted terrain quantities. Partial nodata is explicitly disclosed; all-nodata/no-pixel AOIs fail with actionable messages. Tile/download/processing failures never publish partial results.

The result includes an AOI-masked float32 GeoTIFF at the native geographic grid with nodata -9999, units/datum/source/license tags, and a JSON summary with source tiles, AOI bounds, timestamps, methods, limitations, and attribution. Statistics use native samples. `ui/elevation.py` displays non-editable brown contour vectors with white halos, thin regular lines and heavier index lines every fifth interval, labeled index elevations, hover elevations, and an on-map legend with intervals/range/datum. It replaces the colored raster display. Visibility/opacity controls, metrics, coverage notices, and downloads remain independent of other workflows. Outputs are capped at 20 MiB each and session-only. AOI changes clear results/errors; failed reloads explicitly retain the last successful result. Building edits, pathway work, roads, and viewport must survive analysis and visibility changes.

`analysis/contours.py` uses ContourPy to derive linear isolines from native sample centers with masked quads excluded, then clips lines to the exact AOI and excludes boundary-only segments. Do not bridge holes/nodata or extrapolate to AOI edges. Auto interval targets about twelve levels with a 2 m minimum; users may choose 2/5/10/20/50/100 m. Limits: 100 levels, 5,000 line features, and 200,000 vertices, with actionable errors suggesting a coarser interval. Flat/narrow/all-masked terrain may have no lines and is explained. Finer intervals do not imply better vertical accuracy. Contours are cached on the current session's elevation result by AOI geometry and interval; existing saved GeoTIFF results can be displayed without redownloading FABDEM. Contour GeoJSON retains source/license metadata and regular/index elevations; summary download records interval/method. The worker's legacy PNG artifact remains available internally but is no longer displayed.

Validate native-grid statistics and masking/holes, nodata/no samples, seams/overlapping AOIs, global tile naming, unsupported CRS/resolution, range validation and size limits, corrupt/missing archives, hard timeout, export metadata, source/workspace isolation, AOI invalidation, and overlay controls. Run a live official-source query and inspect browser alignment when available. Do not present this ~30 m terrain estimate as an engineering survey or as detailed building/road surface elevations.

### Phase 5 — Public deployment

Deploy to a shareable URL, initially evaluating Streamlit Community Cloud. Document configuration, secrets, dependencies, and relevant resource limits.

Validate access from a fresh browser without a local Python installation and exercise the deployed AOI-to-results workflow.

## Future considerations and open decisions

Validate provider suitability for public hosting and GlobalMLBuildingFootprints coverage during the appropriate phase. Define AOI size limits, counting semantics, result formats, and processing/resource limits as analysis is introduced. Phase 1 exports all drawn polygons as a FeatureCollection, rejects invalid geometry, and requires date-line-crossing regions to be split. Consider FastAPI, a separate frontend, and workers only when requested or when measured requirements justify a proposed change. Do not implement that migration in advance.
