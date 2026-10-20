"""Topographic isolines from the existing AOI-masked FABDEM GeoTIFF."""

import math

from shapely.geometry import LineString, mapping, shape
from shapely.ops import unary_union

from geoanalysis.core.geometry import aoi_feature_collection
from geoanalysis.services.elevation import ElevationDataError

MAX_LEVELS = 100
MAX_FEATURES = 5000
MAX_VERTICES = 200000


def contour_interval(low, high):
    """Choose a readable interval targeting about twelve levels, minimum 2 m."""
    target = max(2, (high - low) / 12)
    power = 10 ** math.floor(math.log10(target))
    return float(next(multiplier * power for multiplier in (1, 2, 5, 10) if multiplier * power >= target))


def _line_parts(geometry):
    if geometry.geom_type == "LineString":
        return [geometry] if not geometry.is_empty else []
    if geometry.geom_type in {"MultiLineString", "GeometryCollection"}:
        return [part for child in geometry.geoms for part in _line_parts(child)]
    return []


def build_contours(geotiff, collection=None, interval=None):
    """Interpolate native pixel centers without filling holes or missing data.

    Every fifth level is an index contour. Exact AOI clipping prevents lines
    interpolated across concavities from escaping the selected boundary.
    """
    try:
        import contourpy
        import numpy as np
        from rasterio.io import MemoryFile
    except ImportError as error:
        raise ElevationDataError("Topographic dependencies are missing. Install requirements.txt, then reload the app.") from error
    from rasterio.errors import RasterioError

    aoi = None
    if collection is not None:
        if not isinstance(collection, dict) or collection.get("type") != "FeatureCollection":
            raise ValueError("Contours require an AOI FeatureCollection.")
        validated = aoi_feature_collection(collection.get("features", []))
        if not validated["features"]:
            raise ValueError("Select an AOI before displaying contours.")
        aoi = unary_union([shape(f["geometry"]) for f in validated["features"]])
    try:
        with MemoryFile(geotiff) as memory, memory.open() as src:
            if src.crs is None or src.crs.to_epsg() != 4326 or src.count != 1 or src.width * src.height > 200000:
                raise ElevationDataError("Contours require a bounded WGS 84 elevation raster.")
            if src.transform.b or src.transform.d or src.transform.a <= 0 or src.transform.e >= 0:
                raise ElevationDataError("Contour raster has an unsupported grid layout.")
            data = src.read(1, masked=True).astype("float64")
            data = np.ma.masked_invalid(data)
            if data.count() == 0:
                raise ElevationDataError("No valid elevation samples are available for contours.")
            low, high = float(data.min()), float(data.max())
            spacing = contour_interval(low, high) if interval is None else float(interval)
            if not math.isfinite(spacing) or spacing <= 0:
                raise ValueError("Contour interval must be a positive finite number of metres.")
            first, last = math.ceil(low / spacing), math.floor(high / spacing)
            if last - first + 1 > MAX_LEVELS:
                raise ElevationDataError("This interval creates too many contours. Choose a larger contour interval.")
            # Increasing y simplifies the native raster's north-to-south rows.
            x = src.transform.c + (np.arange(src.width) + 0.5) * src.transform.a
            y = (src.transform.f + (np.arange(src.height) + 0.5) * src.transform.e)[::-1]
        features, vertices = [], 0
        if data.shape[0] >= 2 and data.shape[1] >= 2 and high > low and last >= first:
            generator = contourpy.contour_generator(x=x, y=y, z=data[::-1], corner_mask=False, line_type="Separate")
            for number in range(first, last + 1):
                level = number * spacing
                for points in generator.lines(level):
                    if len(points) < 2:
                        continue
                    line = LineString(points)
                    if aoi is not None:
                        line = line.intersection(aoi).difference(aoi.boundary)
                    for part in _line_parts(line):
                        if len(part.coords) < 2 or part.is_empty or not part.is_valid:
                            continue
                        vertices += len(part.coords)
                        if len(features) >= MAX_FEATURES or vertices > MAX_VERTICES:
                            raise ElevationDataError("Contour detail exceeds the display limit. Choose a larger interval or smaller AOI.")
                        features.append({"type": "Feature", "id": f"contour-{number}-{len(features)}",
                                         "geometry": mapping(part),
                                         "properties": {"elevation_m": level, "index": number % 5 == 0,
                                                        "label": f"{level:g} m", "vertical_datum": "EGM2008"}})
        return {"type": "FeatureCollection", "features": features, "interval_m": spacing,
                "index_interval_m": 5 * spacing, "minimum_m": low, "maximum_m": high,
                "method": "Linear isolines between native FABDEM sample centers; masked quads excluded; clipped to AOI.",
                "notice": "Contour spacing does not imply vertical accuracy. No contours are extrapolated through missing data."}
    except RasterioError as error:
        raise ElevationDataError("The saved elevation GeoTIFF could not be read for contours. Rerun FABDEM analysis.") from error
