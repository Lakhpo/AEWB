"""Bounded Overpass building access and multipolygon reconstruction."""

import json
import time

import requests
from shapely.errors import ShapelyError
from shapely.geometry import LineString, MultiLineString, MultiPolygon, Polygon, mapping
from shapely.ops import linemerge

from geoanalysis.core.geometry import aoi_feature_collection
from geoanalysis.services.buildings import BuildingDataError

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
LICENSE = "https://opendatacommons.org/licenses/odbl/1-0/"
ATTRIBUTION = "© OpenStreetMap contributors"
MAX_BYTES = 20 * 1024 * 1024
MAX_ELEMENTS = 10000


def _coordinates(points):
    return [[point["lon"], point["lat"]] for point in points]


def _validate_polygon(polygon):
    # Reuse coordinate/ring validation without silently repairing source shapes.
    geometry = json.loads(json.dumps(mapping(polygon)))
    polygons = geometry["coordinates"] if geometry["type"] == "MultiPolygon" else [geometry["coordinates"]]
    for rings in polygons:
        aoi_feature_collection([{"type": "Feature", "geometry": {"type": "Polygon", "coordinates": rings}}])
    if polygon.is_empty or not polygon.is_valid:
        raise ValueError("Invalid OSM building polygon")
    return geometry


def _rings(members):
    """Join member ways in either direction; reject dangling/branched rings."""
    if not members:
        return []
    lines = [LineString(_coordinates(member["geometry"])) for member in members]
    joined = linemerge(MultiLineString(lines))
    rings = [joined] if joined.geom_type == "LineString" else list(joined.geoms)
    if any(not ring.is_ring for ring in rings):
        raise ValueError("Incomplete multipolygon ring")
    return [Polygon(ring.coords) for ring in rings]


def _relation_polygon(element):
    members = element["members"]
    if any(m.get("type") != "way" or m.get("role", "") not in {"", "outer", "inner"} for m in members):
        raise ValueError("Unsupported building relation member")
    outers = _rings([m for m in members if m.get("role", "") in {"", "outer"}])
    inners = _rings([m for m in members if m.get("role") == "inner"])
    if not outers:
        raise ValueError("Missing outer ring")
    holes = [[] for outer in outers]
    for inner in inners:
        owners = [i for i, outer in enumerate(outers) if outer.contains(inner)]
        if len(owners) != 1:
            raise ValueError("Unassigned courtyard")
        holes[owners[0]].append(list(inner.exterior.coords))
    polygons = [Polygon(outer.exterior.coords, holes[i]) for i, outer in enumerate(outers)]
    return polygons[0] if len(polygons) == 1 else MultiPolygon(polygons)


def parse_buildings(payload):
    """Reject partial results; count a building relation once, not its ways."""
    if not isinstance(payload, dict) or payload.get("remark") or not isinstance(payload.get("elements"), list):
        raise BuildingDataError("OSM returned an incomplete building query. No partial result was saved.")
    elements = payload["elements"]
    if len(elements) > MAX_ELEMENTS:
        raise BuildingDataError("Too many OSM building records. Select a smaller AOI.")
    features, member_ids = [], set()
    try:
        # Relations first so separately tagged member ways do not double-count.
        for element in sorted(elements, key=lambda e: e["type"] != "relation"):
            tags = element.get("tags", {})
            if not tags.get("building") or tags["building"] == "no":
                continue
            identity = f"osm:{element['type']}/{element['id']}"
            if element["type"] == "relation":
                if tags.get("type") != "multipolygon":
                    raise ValueError("Unsupported building relation")
                polygon = _relation_polygon(element)
                member_ids.update(m["ref"] for m in element["members"])
            elif element["type"] == "way":
                if element["id"] in member_ids:
                    continue
                coordinates = _coordinates(element["geometry"])
                if len(coordinates) < 4 or coordinates[0] != coordinates[-1]:
                    raise ValueError("Open building outline")
                polygon = Polygon(coordinates)
            else:
                raise ValueError("Unsupported building record")
            features.append({"type": "Feature", "id": identity,
                             "geometry": _validate_polygon(polygon),
                             "properties": {"origin": "osm", "source": "OpenStreetMap", "tags": tags,
                                            "license": LICENSE, "attribution": ATTRIBUTION}})
    except (KeyError, TypeError, ValueError, AttributeError, ShapelyError) as error:
        raise BuildingDataError("OSM returned invalid or incomplete building geometry. No partial result was saved.") from error
    return features


def load_osm_buildings(bounds):
    """Request full way/member geometry worldwide using the AOI bounding box."""
    west, south, east, north = bounds
    bbox = f"({south},{west},{north},{east})"
    query = (f'[out:json][timeout:40];(way["building"]["building"!="no"]{bbox};'
             f'relation["type"="multipolygon"]["building"]["building"!="no"]{bbox};);out geom;')
    started = time.monotonic()
    try:
        with requests.post(OVERPASS_URL, data={"data": query}, stream=True,
                           headers={"User-Agent": "PetProject/0.1 (local AOI building explorer)"},
                           timeout=(10, 50)) as response:
            response.raise_for_status()
            content = bytearray()
            for chunk in response.iter_content(64 * 1024):
                content.extend(chunk)
                if len(content) > MAX_BYTES or time.monotonic() - started > 60:
                    raise BuildingDataError("OSM building response exceeded its limit. Select a smaller AOI or retry later.")
        payload = json.loads(content)
    except (requests.RequestException, ValueError) as error:
        raise BuildingDataError("OSM buildings could not be loaded. Check your connection or retry when Overpass is less busy.") from error
    return payload
