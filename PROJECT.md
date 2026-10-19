# Pet Project

## Vision and current scope

Pet Project is a Python-based geospatial web application intended for public access through a shareable URL. Users will select geographic regions on satellite imagery and run automated geospatial analysis without installing Python locally.

The initial analytical objective is to identify and count buildings within user-selected Areas of Interest (AOIs), including rural areas. Prefer established building footprint datasets before developing custom roof-detection models.

The current checkpoint covers the AOI-to-building workflow across Phases 2–4: Microsoft footprint retrieval, counting, overlays, downloads, and manual building review/planning. The latest Overture/OSM infrastructure changes have been reverted at the user's request. Keep infrastructure work, further engineering analysis, custom models, architecture migrations, and deployment deferred until requested.

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
| Future vector and raster operations | GeoPandas, Shapely, Rasterio, added when needed |
| Initial hosting candidate | Streamlit Community Cloud |
| Potential later architecture | FastAPI, separate frontend, and background workers |

Runtime dependencies are recorded in `requirements.txt`: Streamlit, Folium, streamlit-folium, Shapely for geometry validation, and requests for source downloads. GeoPandas and Rasterio remain deferred. Deployment compatibility will be validated before hosting.

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
    core/
      geometry.py                   # AOI validation, coordinates, GeoJSON, CRS handling
      building_review.py            # Manual review, planning status, and source reconciliation
    services/
      imagery.py                    # Imagery access/downloads when required
      buildings.py                  # Microsoft partition index and bounded GeoJSONL reads
    analysis/
      analysis.py                   # AOI-driven processing and building analysis
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

This structure reflects existing directories. UI modules implement map/AOI and review controls; core modules validate/reconcile edits; services supply Microsoft footprint data; analysis modules filter and count it. The imagery-download module remains a placeholder. Keep Streamlit-specific state and widgets in `ui`; backend modules accept ordinary Python/geospatial inputs without depending on Streamlit. Map tile display and imagery downloads are separate needs; this workflow does not implement imagery downloads.

## Development roadmap and phase validation

### Phase 1 — Interactive map

Build a browser-based Streamlit application with satellite imagery, zooming, panning, and polygon/rectangle drawing. Capture AOI coordinates and allow GeoJSON export.

Navigation includes enabled-by-default Esri World Boundaries and Places and World Transportation reference overlays for city names, administrative boundaries, roads, and street names, with independent layer toggles. Submitted address/city/place search through Folium's Nominatim geocoder fits the result's bounds and displays a location pin while preserving drawn AOIs. The pin does not create an AOI and is excluded from exports. Street labels depend on zoom and address results depend on dataset coverage. Autocomplete is disabled. Review Nominatim's usage policy before public deployment and use a provider suitable for expected traffic.

Validate map display, both drawing tools, coordinate order, and successful export of a valid selected boundary. Handle missing or invalid selections clearly. Provider choice and required attribution belong to this phase; building analysis belongs to subsequent phases.

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

### Phase 5 — Public deployment

Deploy to a shareable URL, initially evaluating Streamlit Community Cloud. Document configuration, secrets, dependencies, and relevant resource limits.

Validate access from a fresh browser without a local Python installation and exercise the deployed AOI-to-results workflow.

## Future considerations and open decisions

Validate provider suitability for public hosting and GlobalMLBuildingFootprints coverage during the appropriate phase. Define AOI size limits, counting semantics, result formats, and processing/resource limits as analysis is introduced. Phase 1 exports all drawn polygons as a FeatureCollection, rejects invalid geometry, and requires date-line-crossing regions to be split. Consider FastAPI, a separate frontend, and workers only when requested or when measured requirements justify a proposed change. Do not implement that migration in advance.
