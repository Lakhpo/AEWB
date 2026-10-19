# Pet Project

A Streamlit geospatial app for selecting Areas of Interest (AOIs) on satellite imagery and counting buildings using Microsoft GlobalMLBuildingFootprints. Includes manual building corrections, planned buildings, and GeoJSON exports.

## Run locally

Use Python 3.11 or newer (validated with Python 3.12). From the repository root, on Windows:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m streamlit run src/geoanalysis/ui/app.py
```

Open the local URL printed by Streamlit (usually `http://localhost:8501`). On macOS/Linux, create the environment with `python3 -m venv .venv` and use `.venv/bin/python` for the subsequent commands.

## Select an AOI

1. Use the search box in the map's upper-right corner: enter an address or a city with its state or country, press Enter, and choose a result if several appear. For an address, include the house number, street, city, and state or postal code. The map fits the result and shows a location pin. You can also zoom and pan; the map starts over the United States and supports worldwide navigation.
2. Choose the polygon or rectangle tool. Close a polygon by clicking its first vertex.
3. Use the edit/trash tools and click **Save** to commit changes, or use **Clear AOI and building edits** to start over.
4. Look for **Your AOI & GeoJSON** beside the map (below it on narrow displays). A persistent green success message confirms a valid selection. Click **Download AOI GeoJSON** to save `pet-project-aoi.geojson` to your browser's download location, usually Downloads. No file is saved automatically. The expanded **View / copy GeoJSON** preview also lets you copy the data directly. Multiple boundaries export together as a FeatureCollection in WGS 84 `[longitude, latitude]` order. Self-intersections, degenerate polygons, invalid coordinates, and date-line-crossing edges are rejected.

Finishing or editing a boundary preserves the map's location and zoom. Selection confirmation remains until you edit, delete, or clear the boundaries. **Clear AOI and building edits** removes the selection and building workspace while retaining your location.

Selections live in the active Streamlit session in server memory and are not saved permanently. Download boundaries before refreshing or closing the page. Internet access is required for imagery and map assets. Imagery resolution and dates vary by location.

City names, administrative boundaries (including US state lines), and roads appear over the imagery, with detail depending on zoom. Zoom in to see local street names. Use the lower-right layer control to toggle **City names and state boundaries** and **Street names and roads** independently. Address/city search uses OpenStreetMap Nominatim and sends submitted search text to that service; it does not search while you type. Search navigation preserves drawn boundaries; the location pin is not included in exported AOIs. Address coverage varies: if no result appears, include a city/state/postal code, try the street without a house number, or search a nearby city. Service availability depends on your internet connection.

## Run building analysis

After drawing a local AOI, click **Run Analysis**. A building count appears alongside Microsoft source footprint polygons; your view and editable AOI remain in place. Loading can take a few minutes. Changing the AOI clears the review; run again for the new boundary. Panning and zooming retain results.

The count includes all building types, not just houses. Full footprints with interior overlap with your AOI count once, including boundary-crossing buildings; mere edge/point touches do not count. Multiple AOIs are combined and identical footprints deduplicated. Search pins and result footprints are excluded from the **AOI** GeoJSON download.

The Microsoft dataset uses release **2026-08-13** under [CDLA Permissive 2.0](https://cdla.dev/permissive-2-0/). Coverage is incomplete and source imagery dates can differ from the map. A zero count means no matches in available data. Source failures return errors rather than partial counts. Python downloads candidate source files temporarily and filters them locally; your AOI is not uploaded to Microsoft. No separate database or detection model is created.

Use an AOI at most 0.5 degrees across per axis. Runs are bounded to four partitions, 100 MiB compressed, 1 GiB decompressed, three minutes of file processing, and 10,000 matches. A small AOI can still intersect a large source file; try another location if that file exceeds limits. Results are retained only in the current session. The backend requires outbound HTTPS access to Microsoft's dataset hosts.

## Correct buildings and draw project plans

1. Select an AOI. Run analysis for Microsoft's starting inventory; you can draw plans without running it.
2. Above the map, switch **Map tools** to **Buildings**. The blue AOI outline is locked so building edits cannot alter it.
3. Choose **Existing building** to draw a missing building, or **Planned building** to sketch a proposal. Use the polygon or rectangle tool.
4. To remove a false positive, activate the trash tool, click its footprint, then click **Save**. Use the edit tool and **Save** to adjust geometry. Multipart buildings are shown as several editable parts but count once; delete all parts to remove that building entirely.
5. Use **Undo last building edit** if needed. An invalid or outside-AOI draft leaves counts at the last saved review; fix/delete it or choose **Discard unsaved building edits**.
6. Click **Download edited buildings GeoJSON** to save `pet-project-buildings.geojson`. This is separate from the AOI boundary download.

Orange footprints come from Microsoft, green footprints are manually added existing buildings, and purple footprints are planned. The existing-building review count and planned-building count stay separate. The exported GeoJSON preserves `origin`, `status`, source/license metadata, and stable building IDs. Deleted buildings are absent from that export.

Running analysis again for the same AOI preserves manual corrections and plans. Edits are stored in the active session only: **download before refreshing, restarting the server, or changing/clearing the AOI**. Changing the AOI starts a new review. A downloaded file can be inspected in GIS software; re-import into this app is not implemented.

## Validation

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Manual browser checks: verify satellite tiles and labels load; toggle labels; search for a city (try `Madison, Wisconsin`), select a result, and confirm the map moves there. Try an unknown place and check the no-results message. Draw a boundary, search again, and confirm it remains. Pan and zoom; draw each shape type; edit and delete shapes with Save; download and inspect coordinate order; clear the selection and verify export disappears. Confirm multiple shapes remain through reruns and downloading does not clear them.

For street/address navigation, zoom into a neighborhood and toggle **Street names and roads**. Search a public address such as `1600 Pennsylvania Avenue NW, Washington, DC`; verify the map zooms to the result and shows a pin. Then search a city and verify the view fits the city. Export an existing AOI after a search and confirm the pin is not exported.

For manual review, run analysis, switch to Buildings mode, delete one footprint with the trash tool and Save, and verify the existing count drops by one. Undo and verify it returns. Draw a missing existing building, then a planned building; verify only the appropriate counter increases. Pan and switch modes; confirm edits remain and the AOI is unchanged. Run analysis again and verify corrections remain. Download the edited building GeoJSON and check its `origin`/`status` properties. Test an outside-AOI drawing and verify the error and disabled review export until the draft is corrected or discarded.

## Data and project context

The initial basemap uses [Esri World Imagery](https://www.arcgis.com/home/item.html?id=10df2279f9684e4a9f6a7f08febac2a9), with visible map attribution. Review [Esri attribution and usage terms](https://doc.arcgis.com/en/arcgis-online/reference/display-copyrights.htm) before public hosting. This app displays map tiles; it does not download imagery for analysis.

See [PROJECT.md](PROJECT.md) for architecture and roadmap and [AGENTS.md](AGENTS.md) for development instructions.
