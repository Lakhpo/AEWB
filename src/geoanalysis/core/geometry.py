"""Validate drawn AOIs independently of the web interface."""

from copy import deepcopy
from math import isfinite

from shapely.geometry import shape
from shapely.validation import explain_validity


def aoi_feature_collection(drawings: list[dict]) -> dict:
    """Return validated polygon Features in WGS 84 longitude/latitude order.

    All drawn shapes form the selection. Invalid shapes reject the entire
    selection so an export never silently omits part of the user's AOI.
    """
    features = []
    for index, feature in enumerate(drawings, start=1):
        prefix = f"AOI {index}"
        if not isinstance(feature, dict) or feature.get("type") != "Feature":
            raise ValueError(f"{prefix}: expected a GeoJSON Feature.")
        geometry = feature.get("geometry")
        if not isinstance(geometry, dict) or geometry.get("type") != "Polygon":
            raise ValueError(f"{prefix}: draw a polygon or rectangle.")
        rings = geometry.get("coordinates")
        if not isinstance(rings, list) or not rings:
            raise ValueError(f"{prefix}: the boundary is empty.")
        for ring in rings:
            if not isinstance(ring, list) or len(ring) < 4 or ring[0] != ring[-1]:
                raise ValueError(f"{prefix}: the boundary must be a closed ring.")
            for position in ring:
                if not isinstance(position, (list, tuple)) or len(position) != 2:
                    raise ValueError(f"{prefix}: expected longitude/latitude pairs.")
                if any(isinstance(v, bool) or not isinstance(v, (int, float))
                       or not isfinite(v) for v in position):
                    raise ValueError(f"{prefix}: coordinates must be finite numbers.")
                lon, lat = position
                if not -180 <= lon <= 180 or not -90 <= lat <= 90:
                    raise ValueError(f"{prefix}: coordinates are outside WGS 84 bounds.")
            if any(abs(a[0] - b[0]) > 180 for a, b in zip(ring, ring[1:])):
                raise ValueError(f"{prefix}: split boundaries crossing the date line.")
        polygon = shape(geometry)
        if polygon.is_empty or not polygon.is_valid:
            raise ValueError(f"{prefix}: invalid boundary ({explain_validity(polygon)}).")
        features.append({
            "type": "Feature",
            "properties": {"name": prefix},
            "geometry": deepcopy(geometry),
        })
    return {"type": "FeatureCollection", "features": features}
