# Pet Project

A Streamlit geospatial app for selecting Areas of Interest (AOIs) on satellite imagery and counting buildings using Microsoft GlobalMLBuildingFootprints. Includes manual building corrections, planned buildings, Overture/OSM road layers, and GeoJSON exports.

## Run locally

Use Python 3.11 or newer (validated with Python 3.12). From the repository root, on Windows:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m streamlit run src/geoanalysis/ui/app.py
```

Open the local URL printed by Streamlit (usually `http://localhost:8501`). On macOS/Linux, create the environment with `python3 -m venv .venv` and use `.venv/bin/python` for the subsequent commands.

The entry point registers `src` on `PYTHONPATH` so Streamlit watches backend modules as well as UI files during development. If a server started before this fix shows an import error after an update, stop it with Ctrl+C and run the Streamlit command again. Restarting clears session-only selections and edits.

## Select an AOI

To jump directly to coordinates, use **Coordinates (latitude, longitude)** above the map. Paste decimal degrees such as `43.0731, -89.4012`, then click **Go to coordinates** or press Enter. Latitude comes first; use negative values for south or west. The map zooms to the location and adds a red navigation point while preserving AOIs, building edits, and road results. The point stays out of GeoJSON exports. Coordinate search also works before drawing an AOI; degrees/minutes/seconds notation is not supported.

1. Use the search box in the map's upper-right corner: enter an address or a city with its state or country, press Enter, and choose a result if several appear. For an address, include the house number, street, city, and state or postal code. The map fits the result and shows a location pin. You can also zoom and pan; the map starts over the United States and supports worldwide navigation.
2. Choose the polygon or rectangle tool. Close a polygon by clicking its first vertex.
3. Use the edit/trash tools and click **Save** to commit changes, or use **Clear AOI and building edits** to start over.
4. Look for **Your AOI & GeoJSON** beside the map (below it on narrow displays). A persistent green success message confirms a valid selection. Click **Download AOI GeoJSON** to save `pet-project-aoi.geojson` to your browser's download location, usually Downloads. No file is saved automatically. The expanded **View / copy GeoJSON** preview also lets you copy the data directly. Multiple boundaries export together as a FeatureCollection in WGS 84 `[longitude, latitude]` order. Self-intersections, degenerate polygons, invalid coordinates, and date-line-crossing edges are rejected.

Finishing or editing a boundary preserves the map's location and zoom. Selection confirmation remains until you edit, delete, or clear the boundaries. **Clear AOI and building edits** removes the selection, building workspace, and road results while retaining your location.

Selections live in the active Streamlit session in server memory and are not saved permanently. Download boundaries before refreshing or closing the page. Internet access is required for imagery and map assets. Imagery resolution and dates vary by location.

City names, administrative boundaries (including US state lines), and roads appear over the imagery, with detail depending on zoom. Zoom in to see local street names. Use the lower-right layer control to toggle **City names and state boundaries** and **Street names and roads** independently. Address/city search uses OpenStreetMap Nominatim and sends submitted search text to that service; it does not search while you type. Search navigation preserves drawn boundaries; the location pin is not included in exported AOIs. Address coverage varies: if no result appears, include a city/state/postal code, try the street without a house number, or search a nearby city. Service availability depends on your internet connection.

## Run building analysis

After drawing a local AOI, click **Run Analysis**. A building count appears alongside Microsoft source footprint polygons; your view and editable AOI remain in place. Loading can take a few minutes. Changing the AOI clears the review; run again for the new boundary. Panning and zooming retain results.

The count includes all building types, not just houses. Full footprints with interior overlap with your AOI count once, including boundary-crossing buildings; mere edge/point touches do not count. Multiple AOIs are combined and identical footprints deduplicated. Search pins and result footprints are excluded from the **AOI** GeoJSON download.

The Microsoft dataset uses release **2026-08-13** under [CDLA Permissive 2.0](https://cdla.dev/permissive-2-0/). Coverage is incomplete and source imagery dates can differ from the map. A zero count means no matches in available data. Source failures return errors rather than partial counts. Python downloads candidate source files temporarily and filters them locally; your AOI is not uploaded to Microsoft. No separate database or detection model is created.

Use an AOI at most 0.5 degrees across per axis. Runs are bounded to four partitions, 100 MiB compressed, 1 GiB decompressed, three minutes of file processing, and 10,000 matches. A small AOI can still intersect a large source file; try another location if that file exceeds limits. Results are retained only in the current session. The backend requires outbound HTTPS access to Microsoft's dataset hosts.

## Compare OSM building footprints

After selecting an AOI, click **Load OSM buildings** in **OSM building footprints** beside the map. This works independently of Microsoft analysis, including where Microsoft is unavailable. Cyan outlines show OSM buildings; **Show OSM buildings** toggles them. The separate OSM count includes unique full footprints with interior overlap with the AOI, excluding boundary-only touches. Courtyards and multipart buildings are supported; a building relation counts once and its member ways are not counted again.

OSM is a read-only reference layer. Microsoft/manual review counts and OSM counts can overlap and are **not added together**. Automatic matching/merging and importing OSM footprints into the editable review are not implemented. Compare coverage on the map; use the existing Buildings tools to draw a missing footprint into your review if needed. Loading OSM retains Microsoft results, manual corrections/plans, roads, and your viewport. AOI changes clear OSM results. Failed reloads explicitly retain the previous successful OSM layer.

**Download OSM buildings GeoJSON** saves `pet-project-osm-buildings.geojson` separately from AOI and edited-building exports, with original OSM IDs/tags, retrieval time, and license/attribution metadata. Data is from [OpenStreetMap contributors under ODbL](https://www.openstreetmap.org/copyright); follow attribution and applicable share-alike requirements when redistributing OSM or derived databases. No API key is required. This feature sends AOI bounds to `overpass-api.de` on explicit loading. It does not submit your manual building edits.

Use AOIs up to **0.1 degrees per axis**. Queries have a 40-second server timeout, network timeouts, a 60-second streaming check, a 20 MiB response limit, and at most 10,000 returned records. Invalid/incomplete geometries, Overpass remarks, network failures, and resource limits produce errors without partial counts. Data is session-only; download before changing the AOI, refreshing, or restarting. Coverage varies in both rural and urban areas; zero matches do not prove no buildings exist. Building points and `building:part`-only records are excluded. Bounding-box queries may miss crossing buildings with no node inside the bounds. This is not a verified count of houses.

## Correct buildings and draw project plans

1. Select an AOI. Run analysis for Microsoft's starting inventory; you can draw plans without running it.
2. Above the map, switch **Map tools** to **Buildings**. The blue AOI outline is locked so building edits cannot alter it.
3. Choose **Existing building** to draw a missing building, or **Planned building** to sketch a proposal. Use the polygon or rectangle tool.
4. To remove a false positive, activate the trash tool, click its footprint, then click **Save**. Use the edit tool and **Save** to adjust geometry. Multipart buildings are shown as several editable parts but count once; delete all parts to remove that building entirely.
5. Use **Undo last building edit** if needed. An invalid or outside-AOI draft leaves counts at the last saved review; fix/delete it or choose **Discard unsaved building edits**.
6. Click **Download edited buildings GeoJSON** to save `pet-project-buildings.geojson`. This is separate from the AOI boundary download.

Orange footprints come from Microsoft, green footprints are manually added existing buildings, and purple footprints are planned. The existing-building review count and planned-building count stay separate. The exported GeoJSON preserves `origin`, `status`, source/license metadata, and stable building IDs. Deleted buildings are absent from that export.

Running analysis again for the same AOI preserves manual corrections and plans. Edits are stored in the active session only: **download before refreshing, restarting the server, or changing/clearing the AOI**. Changing the AOI starts a new review. A downloaded file can be inspected in GIS software; re-import into this app is not implemented.

## Draw and extend pathways

1. Select an AOI, then switch **Map tools** to **Pathways**. Loading buildings or roads is optional; loaded source roads stay visible as locked references.
2. Choose **Planned pathway** (default) or **Existing pathway** for user-mapped paths. Use the line tool, click vertices, and click the last point again to finish. Pink dashed lines are planned; solid pink lines are user-mapped existing paths.
3. To extend your sketch, activate **Edit**, drag its endpoint farther along your route, and use midpoint handles to insert bends. Click **Save**. To extend a mapped source route, draw a separate connecting sketch from its endpoint; source roads are not editable and endpoints do not automatically snap together.
4. Use **Trash**, click a sketch, and **Save** to remove it. **Undo last pathway edit** restores the previous accepted snapshot, including deletions. Invalid drafts preserve accepted sketches and totals; correct the draft or choose **Discard unsaved pathway edits**.
5. Download **pathway sketches GeoJSON** as `pet-project-pathways.geojson`. It includes stable IDs, user-drawn provenance, existing/planned status, geodesic lengths, and `public_access: unverified`. Pathways stay separate from building, AOI, Overture, and OSM downloads and totals.

Keep sketches inside the AOI and outside its holes; endpoints may meet its boundary. Lines need at least two distinct vertices, at most 2,000 vertices, and cannot cross themselves. Limits are 1,000 sketches per AOI. Geodesic sketch length totals are separate for existing/planned paths; overlapping routes are not merged and lengths are not survey quantities. Sketches do not establish public access or easement rights, including paths marked existing. Drawing and edits remain local session state; nothing is uploaded to OSM or Overture.

Panning, navigation, mode switches, and source reloads retain sketches and building work. Download before changing/clearing the AOI, refreshing, or restarting: sketches are session-only, and re-import is not implemented.

## Load streets and roadways

1. Draw a local AOI (up to 0.1 degrees across per axis). In **Streets & roadways** beside the map, click **Load roads**. Loading may take a few minutes; it runs independently of building analysis.
2. View yellow Overture road/path centerlines, clipped to the AOI. Hover a line for its name, class, and source. Use **Show Overture roads** to toggle them. The panel displays geodesic mapped length in kilometers and the number of source segments, including footpaths/cycleways.
3. Optionally select **Include OSM reference layer**, then click **Load roads** again. Dashed blue OSM lines help compare coverage; toggle them using **Show OSM reference roads**. Overture already includes OSM data, so these sources overlap and are not added together. The displayed length is Overture only.
4. Download **Overture roads GeoJSON** or **OSM roads GeoJSON** separately. Files retain source IDs, classes, names, original access attributes, and attribution. Road features remain separate from AOI and building exports and cannot be edited with the building tools.

Roads use Overture release **2026-09-23.1** and optional live OSM Overpass data under [ODbL and source attribution](https://docs.overturemaps.org/attribution/). These are mapped centerlines, not verified public access or easement boundaries. Lengths are approximate plan-view measurements, not engineering survey quantities. Coverage varies, and no matches does not prove no roads exist.

Panning, zooming, building edits, and road toggles retain results and your viewport. Changing or clearing the AOI clears roads; refreshing/restarting loses session data. Download first. The road worker stops after three minutes and returns actionable errors without partial results. An optional OSM failure leaves Overture available with a warning. A failed reload keeps the last successful result explicitly labeled. Internet access to Overture STAC/S3 and Overpass is required; AOI bounds are sent to those services when loading roads.

## Analyze AOI terrain elevation with FABDEM

Select an AOI, then click **Run FABDEM elevation analysis** in **Terrain elevation · FABDEM** beside the map. This works independently of loading buildings or roads. The first load may take a few minutes; Python retrieves the necessary official University of Bristol tile members without downloading entire regional ZIP archives. There is no API key, and your AOI drawings/manual edits are not uploaded to the provider; requested tile names reveal the broad query region.

View minimum/maximum, mean/median, relief, and valid-data coverage. Elevation displays as a **topographic contour map** over the satellite imagery, with no elevation color fill. Thin brown lines mark regular contours; heavier lines every fifth interval are index contours with elevation labels. Hover any contour to see its elevation in metres. An on-map legend shows the contour/index intervals, elevation range, datum, and attribution. **Contour interval** offers Auto (about twelve levels, minimum 2 m) or 2/5/10/20/50/100 m; **Show FABDEM elevation** and **Contour opacity** control the display. Changes reuse the saved GeoTIFF without another source download. Existing elevation results also work without rerunning analysis.

Contours are linearly interpolated between native pixel centers, clipped to the AOI, and never filled through holes/nodata. Lines can stop short of boundaries where neighboring samples are unavailable. Flat terrain, a large interval, or too few adjacent samples can produce no contour lines; the UI explains this. A finer interval does not improve FABDEM's vertical accuracy. Contour generation is limited to 100 elevation levels, 5,000 line features, and 200,000 vertices; use a larger interval if a detail limit is reached. **Download topographic contours GeoJSON** exports the displayed contours with elevations, index flags, interval metadata, datum, source/license, and attribution.

The summary JSON also includes standard deviation and 5th/95th percentiles, plus the selected contour interval/method. Pixel centers inside the unioned AOI define sample inclusion; statistics are unweighted summaries of valid native-grid samples. Missing-data coverage is explicit; an AOI without valid samples returns an error instead of zero elevation.

**Download FABDEM AOI GeoTIFF** saves `pet-project-fabdem-elevation.tif` at native grid spacing, with outside-AOI/nodata pixels set to -9999 and source/license/datum tags. **Download elevation summary JSON** saves the statistics, coverage, AOI bounds, tile sources, retrieval time, methods, and attribution. Both are separate from boundary, building, pathway, and road exports. Contours remain WGS 84 vectors displayed by Leaflet on the map. Elevations are in **metres relative to EGM2008**, with horizontal coordinates in WGS 84.

[FABDEM V1-2](https://research-information.bris.ac.uk/en/datasets/fabdem-v1-2/) removes building/tree height biases from Copernicus DEM. It estimates ground terrain, **not rooftop surface elevation**, at 1 arc-second spacing (~30 m at the equator). It cannot resolve every small feature and is not an engineering survey. Slope, drainage, and cut/fill are not implemented. The dataset uses [CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/): non-commercial use, attribution, and share-alike obligations apply. Contact the provider for commercial use. Required FABDEM/Copernicus attribution is displayed under the results and embedded in downloads; retain it when sharing outputs.

Prototype limits: AOI bounding-box spans at most **0.1 degrees per axis**, latitudes **85°S–85°N**, at most four source tiles, 256 MiB total transfer, 80 MiB per compressed/expanded tile, 200,000 mosaic pixels, and a three-minute hard analysis timeout. No full-archive fallback or substitute DEM is used. Missing tiles, network/format errors, and limits are actionable failures without partial results. A failed reload explicitly retains the last successful result. Changing the AOI clears elevation; map navigation, source loading, and building/pathway editing retain it. Results are session-only: download before changing the AOI, refreshing, or restarting.

Rasterio is required for elevation and ContourPy for topographic contours. Update older environments with `.\.venv\Scripts\python.exe -m pip install -r requirements.txt`. Missing dependencies produce actionable messages.

## Validation

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Manual browser checks: verify satellite tiles and labels load; toggle labels; search for a city (try `Madison, Wisconsin`), select a result, and confirm the map moves there. Try an unknown place and check the no-results message. Draw a boundary, search again, and confirm it remains. Pan and zoom; draw each shape type; edit and delete shapes with Save; download and inspect coordinate order; clear the selection and verify export disappears. Confirm multiple shapes remain through reruns and downloading does not clear them.

For street/address navigation, zoom into a neighborhood and toggle **Street names and roads**. Search a public address such as `1600 Pennsylvania Avenue NW, Washington, DC`; verify the map zooms to the result and shows a pin. Then search a city and verify the view fits the city. Export an existing AOI after a search and confirm the pin is not exported.

For manual review, run analysis, switch to Buildings mode, delete one footprint with the trash tool and Save, and verify the existing count drops by one. Undo and verify it returns. Draw a missing existing building, then a planned building; verify only the appropriate counter increases. Pan and switch modes; confirm edits remain and the AOI is unchanged. Run analysis again and verify corrections remain. Download the edited building GeoJSON and check its `origin`/`status` properties. Test an outside-AOI drawing and verify the error and disabled review export until the draft is corrected or discarded.

For roads, load a small AOI, verify lines align with imagery and stop at the boundary, hover road names, and toggle each source. Load buildings and make a manual correction; confirm loading/toggling roads retains that correction and the current map position. Download each road source and verify the AOI download still contains only polygons. Change the AOI and confirm old road results disappear. Test with OSM enabled and with an unavailable data connection.

## Data and project context

The initial basemap uses [Esri World Imagery](https://www.arcgis.com/home/item.html?id=10df2279f9684e4a9f6a7f08febac2a9), with visible map attribution. Review [Esri attribution and usage terms](https://doc.arcgis.com/en/arcgis-online/reference/display-copyrights.htm) before public hosting. This app displays map tiles; it does not download imagery for analysis.

See [PROJECT.md](PROJECT.md) for architecture and roadmap and [AGENTS.md](AGENTS.md) for development instructions.
