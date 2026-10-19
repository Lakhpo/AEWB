"""Clip road centerlines to AOIs and measure each source independently."""

from copy import deepcopy
import math

from shapely.geometry import mapping, shape
from shapely.errors import ShapelyError
from shapely.ops import unary_union

from geoanalysis.core.geometry import aoi_feature_collection
from geoanalysis.services.roads import (
    ATTRIBUTION, LICENSE, RELEASE, RoadDataError, load_osm_roads, load_overture_roads,
)


def _lines(geometry):
    if geometry.geom_type == "LineString":
        return [geometry] if not geometry.is_empty else []
    if geometry.geom_type in {"MultiLineString", "GeometryCollection"}:
        return [line for part in geometry.geoms for line in _lines(part)]
    return []


def _clip_features(features, aoi, origin, geod):
    try:
        return _validated_features(features, aoi, origin, geod)
    except (KeyError, TypeError, ValueError, AttributeError, ShapelyError) as error:
        raise RoadDataError(f"{origin} returned unreadable road data. No partial result was saved.") from error


def _validated_features(features, aoi, origin, geod):
    clipped, identities = [], set()
    for feature in features:
        geometry = shape(feature["geometry"])
        if geometry.geom_type not in {"LineString", "MultiLineString"} or geometry.is_empty or not geometry.is_valid:
            raise RoadDataError(f"{origin} returned invalid road geometry. No partial result was saved.")
        for line in _lines(geometry):
            for lon, lat, *extra in line.coords:
                if extra or not math.isfinite(lon) or not math.isfinite(lat) or not -180 <= lon <= 180 or not -90 <= lat <= 90:
                    raise RoadDataError(f"{origin} returned invalid road coordinates.")
            if any(abs(a[0] - b[0]) > 180 for a, b in zip(line.coords, list(line.coords)[1:])):
                raise RoadDataError("Date-line-crossing source roads are not supported in this version.")
        # Remove boundary-only lines and point contacts; retain positive length
        # inside any AOI, including multipart intersections and holes.
        parts = _lines(geometry.intersection(aoi).difference(aoi.boundary))
        if not parts:
            continue
        geometry = unary_union(parts)
        identity = feature["id"]
        if identity in identities:
            continue
        identities.add(identity)
        props = deepcopy(feature.get("properties", {}))
        name = (props.get("names") or {}).get("primary") or "Unnamed road/path"
        props.update({"origin": origin, "name": name, "class": props.get("class") or "unknown",
                      "length_m": abs(geod.geometry_length(geometry)), "clipped_to_aoi": True,
                      "license": LICENSE, "attribution": ATTRIBUTION if origin == "overture" else "© OpenStreetMap contributors",
                      "source_release": RELEASE if origin == "overture" else "live query",
                      "access_scope": "Source tags/rules apply to the original source way/segment; fractions are not remapped to clipped geometry."})
        clipped.append({"type": "Feature", "id": identity, "geometry": mapping(geometry), "properties": props})
    return {"type": "FeatureCollection", "features": clipped, "license": LICENSE,
            "source": origin, "source_release": RELEASE if origin == "overture" else "live query",
            "attribution": ATTRIBUTION if origin == "overture" else "© OpenStreetMap contributors"}


def find_roads(collection, include_osm=False, progress=None):
    """Return Overture roads and an optional independent OSM reference layer.

    Sources intentionally remain separate: Overture already includes OSM, so
    their lengths/counts must not be added together. No country filter is needed
    for either source; the selected AOI supplies the query location worldwide.
    """
    if not isinstance(collection, dict) or collection.get("type") != "FeatureCollection":
        raise ValueError("Road analysis requires an AOI GeoJSON FeatureCollection.")
    validated = aoi_feature_collection(collection.get("features", []))
    if not validated["features"]:
        raise ValueError("Draw an AOI before loading roads.")
    aoi = unary_union([shape(f["geometry"]) for f in validated["features"]])
    west, south, east, north = aoi.bounds
    if east - west > 0.1 or north - south > 0.1:
        raise ValueError("Road loading supports local AOIs up to 0.1 degrees across per axis. Select a smaller area.")
    try:
        from pyproj import Geod
    except ImportError as error:
        raise RoadDataError("Road measurement dependencies are missing. Install requirements.txt, then restart Streamlit.") from error
    geod = Geod(ellps="WGS84")
    if progress:
        progress("Loading Overture road centerlines for your AOI…")
    overture = _clip_features(load_overture_roads(aoi.bounds), aoi, "overture", geod)
    osm, warnings = None, []
    if include_osm:
        if progress:
            progress("Loading the optional OSM reference layer…")
        try:
            osm = _clip_features(load_osm_roads(aoi.bounds), aoi, "osm", geod)
        except RoadDataError as error:
            warnings.append(f"OSM reference unavailable: {error} Overture roads are still available.")
    return {"overture": overture, "osm": osm, "release": RELEASE, "warnings": warnings,
            "count": len(overture["features"]),
            "length_m": sum(f["properties"]["length_m"] for f in overture["features"])}
