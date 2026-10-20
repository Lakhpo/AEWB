"""Select OSM buildings independently of Microsoft's inventory and review."""

from datetime import datetime, timezone

from shapely.geometry import shape
from shapely.ops import unary_union

from geoanalysis.core.geometry import aoi_feature_collection
from geoanalysis.services.osm_buildings import ATTRIBUTION, LICENSE, load_osm_buildings, parse_buildings


def find_osm_buildings(collection):
    """Count full unique footprints with AOI interior overlap; never add sources."""
    if not isinstance(collection, dict) or collection.get("type") != "FeatureCollection":
        raise ValueError("OSM building analysis requires an AOI FeatureCollection.")
    validated = aoi_feature_collection(collection.get("features", []))
    if not validated["features"]:
        raise ValueError("Draw an AOI before loading OSM buildings.")
    aoi = unary_union([shape(f["geometry"]) for f in validated["features"]])
    west, south, east, north = aoi.bounds
    if east - west > 0.1 or north - south > 0.1:
        raise ValueError("OSM building loading supports AOIs up to 0.1 degrees across per axis. Select a smaller area.")
    payload = load_osm_buildings(aoi.bounds)
    features, seen, source_ids = [], set(), set()
    for feature in parse_buildings(payload):
        polygon = shape(feature["geometry"])
        identity = polygon.normalize().wkb
        if identity in seen or feature["id"] in source_ids or not aoi.relate_pattern(polygon, "T********"):
            continue
        seen.add(identity)
        source_ids.add(feature["id"])
        features.append(feature)
    collection = {"type": "FeatureCollection", "features": features,
                  "source": "OpenStreetMap", "license": LICENSE, "attribution": ATTRIBUTION,
                  "retrieved_at": datetime.now(timezone.utc).isoformat(),
                  "osm_timestamp": payload.get("osm3s", {}).get("timestamp_osm_base"),
                  "counting_rule": "Unique full footprints with AOI interior overlap; separate from Microsoft and review counts."}
    return {"geojson": collection, "count": len(features)}
