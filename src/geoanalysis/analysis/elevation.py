"""AOI terrain statistics and masked FABDEM raster artifacts."""

from contextlib import ExitStack
from datetime import datetime, timezone
import importlib.util
import io
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile

from shapely.geometry import mapping, shape
from shapely.ops import unary_union

from geoanalysis.core.geometry import aoi_feature_collection
from geoanalysis.services.elevation import (
    ATTRIBUTION, LICENSE, MAX_SECONDS, RELEASE, SOURCE_URL, ElevationDataError, fabdem_tiles, tile_sources,
)

NODATA = -9999.0
MAX_PIXELS = 200000
MAX_OUTPUT_BYTES = 20 * 1024 * 1024


def validate_elevation_aoi(collection):
    if not isinstance(collection, dict) or collection.get("type") != "FeatureCollection":
        raise ValueError("Elevation analysis requires an AOI FeatureCollection.")
    collection = aoi_feature_collection(collection.get("features", []))
    if not collection["features"]:
        raise ValueError("Draw an AOI before running elevation analysis.")
    aoi = unary_union([shape(f["geometry"]) for f in collection["features"]])
    west, south, east, north = aoi.bounds
    if east - west > 0.1 or north - south > 0.1:
        raise ValueError("FABDEM analysis supports AOIs up to 0.1 degrees across per axis. Select a smaller local area.")
    if south < -85 or north > 85:
        raise ValueError("This map-based elevation analysis supports latitudes between 85°S and 85°N.")
    return collection, aoi


def summarize_raster(data, transform, aoi):
    """Mask by pixel centers, including holes; disclose every missing sample."""
    import numpy as np
    from rasterio.features import geometry_mask

    selected = geometry_mask([mapping(aoi)], out_shape=data.shape, transform=transform,
                             invert=True, all_touched=False)
    total = int(selected.sum())
    if not total:
        raise ElevationDataError("This AOI contains no FABDEM pixel centers at ~30 m spacing. Draw a larger area.")
    valid = selected & np.isfinite(data) & (data != NODATA)
    values = data[valid].astype("float64")
    if not values.size:
        raise ElevationDataError("FABDEM has no valid elevation samples in this AOI. Coverage may be missing or nodata.")
    result = np.where(valid, data, NODATA).astype("float32")
    stats = {"minimum_m": float(values.min()), "maximum_m": float(values.max()),
             "mean_m": float(values.mean()), "median_m": float(np.median(values)),
             "stddev_m": float(values.std()), "relief_m": float(values.max() - values.min()),
             "p05_m": float(np.percentile(values, 5)), "p95_m": float(np.percentile(values, 95)),
             "valid_pixels": int(values.size), "selected_pixels": total,
             "nodata_pixels": total - int(values.size), "coverage_percent": float(100 * values.size / total)}
    return result, stats


def _render_preview(data, transform, stats):
    """Reproject the display to Web Mercator; keep statistics on native samples."""
    import numpy as np
    from PIL import Image
    from rasterio.transform import array_bounds
    from rasterio.warp import calculate_default_transform, reproject, Resampling

    height, width = data.shape
    west, south, east, north = array_bounds(height, width, transform)
    display_transform, cols, rows = calculate_default_transform("EPSG:4326", "EPSG:3857", width, height,
                                                                west, south, east, north)
    if rows * cols > 1000000:
        raise ElevationDataError("Elevation preview exceeds the display limit.")
    display = np.full((rows, cols), NODATA, dtype="float32")
    reproject(data, display, src_transform=transform, src_crs="EPSG:4326", src_nodata=NODATA,
              dst_transform=display_transform, dst_crs="EPSG:3857", dst_nodata=NODATA,
              resampling=Resampling.nearest)
    # Return bounds of the actual projected display, not the rounded source box.
    from rasterio.warp import transform_bounds
    display_bounds = transform_bounds("EPSG:3857", "EPSG:4326", *array_bounds(rows, cols, display_transform))
    low, high = stats["minimum_m"], stats["maximum_m"]
    scaled = np.clip((display - low) / (high - low) if high > low else np.full_like(display, 0.5), 0, 1)
    colors = np.array([[32, 75, 130], [35, 155, 135], [222, 208, 108], [150, 95, 65], [250, 250, 245]])
    rgba = np.zeros((*display.shape, 4), dtype="uint8")
    for channel in range(3):
        rgba[:, :, channel] = np.interp(scaled, np.linspace(0, 1, len(colors)), colors[:, channel]).astype("uint8")
    rgba[:, :, 3] = np.where(display != NODATA, 210, 0)
    output = io.BytesIO()
    Image.fromarray(rgba).save(output, format="PNG")
    w, s, e, n = display_bounds
    return output.getvalue(), [[s, w], [n, e]]


def analyze_elevation(collection):
    """Worker implementation: read source tiles, mosaic windows, mask, export."""
    import numpy as np
    import rasterio
    from rasterio.io import MemoryFile
    from rasterio.merge import merge
    from rasterio.windows import from_bounds, Window, transform as window_transform

    collection, aoi = validate_elevation_aoi(collection)
    sources = tile_sources(aoi.bounds)
    with ExitStack() as stack:
        read_tile = stack.enter_context(fabdem_tiles(sources))
        datasets = []
        for source in sources:
            content = read_tile(source)
            with MemoryFile(content) as tile, tile.open() as src:
                if (src.crs != rasterio.crs.CRS.from_epsg(4326) or src.count != 1
                        or src.width > 4000 or src.height > 4000 or src.transform.b or src.transform.d
                        or src.transform.a <= 0 or src.transform.e >= 0
                        or not math.isclose(src.res[0], 1 / 3600, rel_tol=0.01)
                        or not math.isclose(src.res[1], 1 / 3600, rel_tol=0.01)):
                    raise ElevationDataError("FABDEM returned an unexpected raster CRS, resolution, or layout.")
                west, south = max(aoi.bounds[0], src.bounds.left), max(aoi.bounds[1], src.bounds.bottom)
                east, north = min(aoi.bounds[2], src.bounds.right), min(aoi.bounds[3], src.bounds.top)
                if west >= east or south >= north:
                    continue
                window = from_bounds(west, south, east, north, transform=src.transform)
                col, row = math.floor(window.col_off), math.floor(window.row_off)
                window = Window(col, row, math.ceil(window.col_off + window.width) - col,
                                math.ceil(window.row_off + window.height) - row).intersection(Window(0, 0, src.width, src.height))
                values = src.read(1, window=window, masked=True).filled(NODATA).astype("float32")
                if values.size > MAX_PIXELS:
                    raise ElevationDataError("Elevation raster exceeds the local pixel limit.")
                values[~np.isfinite(values)] = NODATA
                profile = {"driver": "GTiff", "height": values.shape[0], "width": values.shape[1],
                           "count": 1, "dtype": "float32", "crs": "EPSG:4326", "nodata": NODATA,
                           "transform": window_transform(window, src.transform)}
                cropped = stack.enter_context(MemoryFile())
                with cropped.open(**profile) as dst:
                    dst.write(values, 1)
                datasets.append(stack.enter_context(cropped.open()))
            del content
        if not datasets:
            raise ElevationDataError("No FABDEM rasters overlap this AOI.")
        mosaic, transform = merge(datasets, nodata=NODATA, dtype="float32")
        if mosaic[0].size > MAX_PIXELS:
            raise ElevationDataError("Elevation mosaic exceeds the local pixel limit.")
        data, stats = summarize_raster(mosaic[0], transform, aoi)
    summary = {"source": RELEASE, "source_url": SOURCE_URL, "license": LICENSE, "attribution": ATTRIBUTION,
               "retrieved_at": datetime.now(timezone.utc).isoformat(), "horizontal_crs": "EPSG:4326",
               "vertical_datum": "EGM2008 (EPSG:3855)", "units": "metres",
               "aoi_bounds": list(aoi.bounds),
               "grid_spacing_arcseconds": 1, "statistics": stats, "source_tiles": sources,
               "sampling": "Native pixel centers inside the unioned AOI; holes excluded; unweighted valid-pixel statistics.",
               "modifications": "Tiles mosaicked, cropped and AOI-masked; preview reprojected to Web Mercator.",
               "limitations": "Terrain estimate with forest/building biases removed; ~30 m at equator, not a roof surface or engineering survey."}
    with MemoryFile() as output:
        with output.open(driver="GTiff", width=data.shape[1], height=data.shape[0], count=1,
                         dtype="float32", crs="EPSG:4326", transform=transform, nodata=NODATA,
                         compress="deflate") as dst:
            dst.write(data, 1)
            dst.update_tags(SOURCE=RELEASE, SOURCE_URL=SOURCE_URL, LICENSE=LICENSE, ATTRIBUTION=ATTRIBUTION,
                            VERTICAL_DATUM="EGM2008 (EPSG:3855)", UNITS="metres", AREA_OR_POINT="Point",
                            MODIFICATIONS=summary["modifications"])
        geotiff = output.read()
    png, bounds = _render_preview(data, transform, stats)
    summary["overlay_bounds"] = bounds
    return {"summary": summary, "geotiff": geotiff, "preview_png": png}


def find_elevation(collection):
    """Enforce a hard subprocess deadline and publish only complete artifacts."""
    collection, _ = validate_elevation_aoi(collection)
    if importlib.util.find_spec("rasterio") is None:
        raise ElevationDataError("Elevation dependencies are missing. Install requirements.txt and restart Streamlit.")
    with tempfile.TemporaryDirectory(prefix="pet-project-elevation-") as directory:
        folder = Path(directory)
        (folder / "aoi.json").write_text(json.dumps(collection), encoding="utf-8")
        environment = os.environ.copy()
        root = str(Path(__file__).resolve().parents[2])
        environment["PYTHONPATH"] = os.pathsep.join(filter(None, [root, environment.get("PYTHONPATH")]))
        try:
            completed = subprocess.run([sys.executable, "-m", "geoanalysis.analysis.elevation", "--worker", directory],
                                       env=environment, capture_output=True, text=True, timeout=MAX_SECONDS,
                                       creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
        except subprocess.TimeoutExpired as error:
            raise ElevationDataError("FABDEM analysis timed out after three minutes. Retry later or select a smaller AOI.") from error
        except OSError as error:
            raise ElevationDataError("The elevation worker could not start. Check your Python environment.") from error
        try:
            summary_path = folder / "summary.json"
            if completed.returncode or not summary_path.exists() or summary_path.stat().st_size > 100000:
                raise ElevationDataError("FABDEM analysis could not finish. Check dependencies and connection, then retry.")
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            if summary.get("error"):
                raise ElevationDataError(summary["error"])
            artifacts = {"summary": summary}
            for key, name in (("geotiff", "elevation.tif"), ("preview_png", "preview.png")):
                file = folder / name
                if not file.exists() or not 0 < file.stat().st_size <= MAX_OUTPUT_BYTES:
                    raise ElevationDataError("Elevation output was incomplete or oversized. No partial result was saved.")
                artifacts[key] = file.read_bytes()
            return artifacts
        except (OSError, ValueError, AttributeError) as error:
            raise ElevationDataError("Elevation worker output could not be read completely.") from error


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] != "--worker":
        raise SystemExit("Use find_elevation from the application.")
    folder = Path(sys.argv[2])
    try:
        result = analyze_elevation(json.loads((folder / "aoi.json").read_text(encoding="utf-8")))
        (folder / "elevation.tif").write_bytes(result["geotiff"])
        (folder / "preview.png").write_bytes(result["preview_png"])
        summary = result["summary"]
    except (ElevationDataError, ValueError) as error:
        summary = {"error": str(error)}
    except ImportError:
        summary = {"error": "Elevation dependencies are missing. Install requirements.txt and restart Streamlit."}
    except Exception:
        summary = {"error": "FABDEM raster processing failed. Source data may be invalid; no partial result was saved."}
    (folder / "summary.json").write_text(json.dumps(summary, allow_nan=False), encoding="utf-8")
