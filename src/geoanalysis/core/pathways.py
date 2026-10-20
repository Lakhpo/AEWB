"""Validate user pathway sketches independently of map widgets and sources."""

from copy import deepcopy
import math

from pyproj import Geod
from shapely.geometry import shape
from shapely.ops import unary_union

from geoanalysis.core.geometry import aoi_feature_collection

MAX_PATHWAYS = 1000
MAX_VERTICES = 2000


def validate_pathways(features, aois):
    """Accept a complete snapshot or reject it without changing the last review.

    Sketches must stay within the AOI, with some line inside its interior.
    Public access is always unverified, including user-mapped existing paths.
    """
    validated = aoi_feature_collection(aois)
    if not validated["features"]:
        raise ValueError("Select an AOI before drawing pathways.")
    if not isinstance(features, list) or len(features) > MAX_PATHWAYS:
        raise ValueError("Use at most 1,000 pathways per AOI.")
    aoi = unary_union([shape(f["geometry"]) for f in validated["features"]])
    geod = Geod(ellps="WGS84")
    result, ids, shapes = [], set(), set()
    for feature in features:
        if not isinstance(feature, dict) or feature.get("type") != "Feature":
            raise ValueError("Expected a pathway GeoJSON Feature.")
        geometry = feature.get("geometry", {})
        if not isinstance(geometry, dict) or geometry.get("type") != "LineString":
            raise ValueError("Use the line tool to draw a pathway.")
        coordinates = geometry.get("coordinates")
        if not isinstance(coordinates, list) or not 2 <= len(coordinates) <= MAX_VERTICES:
            raise ValueError("Each pathway needs 2 to 2,000 vertices.")
        for point in coordinates:
            if (not isinstance(point, (list, tuple)) or len(point) != 2
                    or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in point)
                    or not -180 <= point[0] <= 180 or not -90 <= point[1] <= 90):
                raise ValueError("Pathway coordinates must be finite WGS 84 longitude/latitude pairs.")
        if any(abs(a[0] - b[0]) > 180 or a == b for a, b in zip(coordinates, coordinates[1:])):
            raise ValueError("Remove repeated vertices and split date-line-crossing pathways.")
        line = shape(geometry)
        if not line.is_valid or not line.is_simple or line.is_empty:
            raise ValueError("A pathway must be a valid line without self-crossings.")
        if not aoi.covers(line) or not aoi.relate_pattern(line, "T********"):
            raise ValueError("Keep pathways inside your AOI, outside its holes. Endpoints may meet its boundary.")
        props = feature.get("properties", {})
        if not isinstance(props, dict):
            raise ValueError("Invalid pathway properties.")
        identity = props.get("review_id") or feature.get("id")
        status = props.get("status")
        if not isinstance(identity, str) or not identity or status not in {"existing", "planned"}:
            raise ValueError("Each pathway needs an ID and an existing or planned status. Reload the pathway editor.")
        signature = line.normalize().wkb
        if identity in ids or signature in shapes:
            raise ValueError("Remove duplicate pathways or repeated pathway IDs, then Save.")
        ids.add(identity)
        shapes.add(signature)
        result.append({"type": "Feature", "id": identity, "geometry": deepcopy(geometry),
                       "properties": {"review_id": identity, "role": "pathway", "origin": "manual",
                                      "source": "User drawn", "status": status, "public_access": "unverified",
                                      "length_m": abs(geod.geometry_length(line))}})
    return sorted(result, key=lambda f: f["id"])


def pathway_collection(features):
    """Separate pathway export with explicit access/provenance semantics."""
    return {"type": "FeatureCollection", "features": deepcopy(features),
            "source": "User drawn pathway sketches", "crs_description": "WGS 84 longitude, latitude",
            "public_access": "unverified",
            "notice": "Sketches do not establish public access, easement rights, or surveyed routes."}
