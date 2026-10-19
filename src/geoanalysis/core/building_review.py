"""Manual footprint review and planning, independent of Streamlit."""

from copy import deepcopy
import hashlib
import json

from shapely.geometry import shape, mapping
from shapely.ops import unary_union

from geoanalysis.core.geometry import aoi_feature_collection


def source_buildings(features):
    """Copy source footprints into the editable review, retaining source IDs."""
    result = []
    for feature in features:
        feature = deepcopy(feature)
        feature["id"] = feature.get("id") or hashlib.sha256(shape(feature["geometry"]).normalize().wkb).hexdigest()
        feature["properties"] = dict(feature.get("properties", {}),
                                     origin="microsoft", status="existing", role="building")
        result.append(feature)
    return result


def editing_parts(features):
    """Leaflet.Draw requires Polygon layers; preserve multipart building IDs."""
    result = []
    for feature in features:
        geometry = feature["geometry"]
        polygons = geometry["coordinates"] if geometry["type"] == "MultiPolygon" else [geometry["coordinates"]]
        for index, polygon in enumerate(polygons):
            part = deepcopy(feature)
            part["id"] = f"{feature['id']}:part:{index}"
            part["properties"]["review_id"] = feature["id"]
            part["geometry"] = {"type": "Polygon", "coordinates": polygon}
            result.append(part)
    return result


def validate_building_edits(parts, aois, originals):
    """Validate a complete editor snapshot and reassemble multipart buildings.

    Every part must overlap the AOI interior. All-or-nothing validation avoids
    publishing a partial review when a newly drawn footprint is invalid.
    """
    aoi = unary_union([shape(f["geometry"]) for f in aoi_feature_collection(aois)["features"]])
    baseline = {f["id"]: f for f in source_buildings(originals)}
    grouped = {}
    for feature in parts:
        aoi_feature_collection([feature])
        props = feature.get("properties", {})
        identity = props.get("review_id") or feature.get("id")
        if not isinstance(identity, str) or not identity:
            raise ValueError("A footprint has no building ID. Switch to AOI mode and back to reload the editor.")
        if props.get("status") not in {"existing", "planned"}:
            raise ValueError("A footprint needs an existing or planned status.")
        grouped.setdefault(identity, []).append(feature)
    result = []
    seen = set()
    for identity, pieces in grouped.items():
        merged = unary_union([shape(piece["geometry"]) for piece in pieces])
        if not aoi.relate_pattern(merged, "T********"):
            raise ValueError("Every building must overlap the AOI. Move or delete the footprint outside your project area, then Save.")
        status = pieces[0]["properties"]["status"]
        signature = (merged.normalize().wkb, status)
        if signature in seen:
            raise ValueError("Two buildings have identical footprints and status. Delete the duplicate, then Save.")
        seen.add(signature)
        original = baseline.get(identity)
        props = dict(original["properties"] if original else {},
                     role="building", status=status, origin="microsoft" if original else "manual")
        if original:
            props["manually_edited"] = not merged.equals(shape(original["geometry"]))
        else:
            props["source"] = "User drawn"
        result.append({"type": "Feature", "id": identity, "properties": props,
                       "geometry": json.loads(json.dumps(mapping(merged)))})
    return sorted(result, key=lambda f: f["id"])


def merge_analysis(features, reviewed, removed_ids):
    """Refresh source data while preserving manual additions/edits/removals."""
    current = {f["id"]: f for f in reviewed}
    merged = [deepcopy(current.get(f["id"], f)) for f in source_buildings(features)
              if f["id"] not in removed_ids]
    merged.extend(deepcopy(f) for f in reviewed if f["properties"]["origin"] == "manual")
    return merged


def review_counts(features):
    return {
        "existing": sum(f["properties"]["status"] == "existing" for f in features),
        "planned": sum(f["properties"]["status"] == "planned" for f in features),
    }
