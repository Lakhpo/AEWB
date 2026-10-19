"""AOI-driven building footprint selection; independent of Streamlit."""

import hashlib

from shapely import normalize
from shapely.errors import ShapelyError
from shapely.geometry import shape
from shapely.ops import unary_union
from shapely.prepared import prep

from geoanalysis.core.geometry import aoi_feature_collection
from geoanalysis.services.buildings import (
    BuildingDataError, RELEASE, SOURCE_URL, iter_footprints, load_index, select_partitions,
)

MAX_BUILDINGS = 10000


def find_buildings(collection, progress=None):
    """Return full footprints overlapping any AOI interior, each counted once.

    Boundary-crossing buildings count; mere edge/point touches do not. Multiple
    overlapping AOIs are unioned. A result is returned only after all selected
    source files have been processed successfully.
    """
    if not isinstance(collection, dict) or collection.get("type") != "FeatureCollection":
        raise ValueError("Analysis requires an AOI GeoJSON FeatureCollection.")
    validated = aoi_feature_collection(collection.get("features", []))
    if not validated["features"]:
        raise ValueError("Draw an AOI before running analysis.")
    aoi = unary_union([shape(f["geometry"]) for f in validated["features"]])
    west, south, east, north = aoi.bounds
    if east - west > 0.5 or north - south > 0.5:
        raise ValueError("This AOI is too large for this version. Select a neighborhood or smaller local project area.")
    partitions = select_partitions(aoi, load_index())
    if progress:
        progress(f"Found {len(partitions)} source file(s). Filtering building footprints…")
    prepared = prep(aoi)
    features, seen = [], set()
    skipped = scanned = 0
    for feature in iter_footprints(partitions, progress):
        scanned += 1
        try:
            if not isinstance(feature, dict) or not isinstance(feature.get("geometry"), dict):
                skipped += 1
                continue
            if feature["geometry"].get("type") not in {"Polygon", "MultiPolygon"}:
                skipped += 1
                continue
            geometry = shape(feature["geometry"])
            if geometry.geom_type not in {"Polygon", "MultiPolygon"} or geometry.is_empty or not geometry.is_valid:
                skipped += 1
                continue
            if not prepared.intersects(geometry) or not aoi.relate_pattern(geometry, "T********"):
                continue
            identity = hashlib.sha256(normalize(geometry).wkb).hexdigest()
            if identity in seen:
                continue
            seen.add(identity)
            if len(seen) > MAX_BUILDINGS:
                raise BuildingDataError("More than 10,000 footprints matched. Select a smaller AOI to display a complete result.")
            features.append({
                "type": "Feature", "id": identity,
                "geometry": feature["geometry"],
                "properties": {"source": "Microsoft GlobalMLBuildingFootprints"},
            })
        except (KeyError, TypeError, ValueError, ShapelyError):
            skipped += 1
    return {
        "geojson": {"type": "FeatureCollection", "features": features},
        "count": len(features), "partitions": len(partitions),
        "scanned": scanned, "skipped": skipped,
        "release": RELEASE, "source": SOURCE_URL,
    }
