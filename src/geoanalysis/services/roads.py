"""Bounded road-source access, independent of Streamlit.

Overture runs in a subprocess so cloud-client initialization and scanning have
an enforceable deadline. Only an explicit analysis action calls these services.
"""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time

import requests

RELEASE = "2026-09-23.1"
MAX_SECONDS = 180
MAX_SCANNED = 30000
MAX_FEATURES = 10000
MAX_BYTES = 20 * 1024 * 1024
OVERPASS_URL = "https://overpass-api.de/api/interpreter"
LICENSE = "https://opendatacommons.org/licenses/odbl/1-0/"
ATTRIBUTION = "© OpenStreetMap contributors, Overture Maps Foundation"


class RoadDataError(RuntimeError):
    """Road data could not be retrieved completely."""


def load_overture_roads(bounds):
    """Return Overture road Features, with a hard end-to-end query timeout."""
    with tempfile.TemporaryDirectory(prefix="pet-project-roads-") as directory:
        output = Path(directory) / "roads.json"
        try:
            completed = subprocess.run(
                [sys.executable, str(Path(__file__).resolve()), "--overture-worker",
                 json.dumps(list(bounds)), str(output)],
                capture_output=True, text=True, timeout=MAX_SECONDS,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            )
        except subprocess.TimeoutExpired as error:
            raise RoadDataError("Road loading timed out after three minutes. Try a smaller AOI or retry later.") from error
        except OSError as error:
            raise RoadDataError("The road data reader could not start. Check your Python environment.") from error
        if completed.returncode or not output.exists():
            raise RoadDataError("Overture roads could not be loaded. Check internet access and install requirements.txt, then retry.")
        if output.stat().st_size > MAX_BYTES:
            raise RoadDataError("Road data exceeds the display limit. Select a smaller AOI.")
        try:
            payload = json.loads(output.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise RoadDataError("The Overture reader returned an incomplete response. Retry loading roads.") from error
        if not isinstance(payload, dict):
            raise RoadDataError("The Overture reader returned an invalid response.")
        if payload.get("error"):
            raise RoadDataError(payload["error"])
        features = payload.get("features")
        if not isinstance(features, list) or len(features) > MAX_FEATURES:
            raise RoadDataError("The Overture reader returned an invalid or oversized result.")
        return features


def _read_overture(bounds):
    """Read only transportation road subtype; rail and water are excluded."""
    from overturemaps import record_batch_reader
    from shapely import from_wkb
    from shapely.geometry import mapping

    reader = record_batch_reader(
        "segment", bbox=tuple(bounds), release=RELEASE, stac=True,
        connect_timeout=10, request_timeout=30,
    )
    # The client uses None for both no STAC files and failed reader creation.
    # Never silently convert an ambiguous response into a zero-road result.
    if reader is None:
        raise RoadDataError("Overture returned no readable road data for this AOI. Coverage or data access may be unavailable.")
    features, scanned = [], 0
    fields = {"id", "geometry", "subtype", "class", "subclass", "names", "sources",
              "access_restrictions", "road_surface", "road_flags", "level_rules", "width_rules"}
    try:
        for batch in reader:
            scanned += batch.num_rows
            if scanned > MAX_SCANNED:
                raise RoadDataError("Too many transportation records. Select a smaller AOI.")
            for row in batch.select([name for name in batch.schema.names if name in fields]).to_pylist():
                if row.get("subtype") != "road":
                    continue
                try:
                    geometry = mapping(from_wkb(row.pop("geometry")))
                except (ValueError, TypeError) as error:
                    raise RoadDataError("Overture returned unreadable road geometry. No partial result was saved.") from error
                identity = row.pop("id")
                features.append({"type": "Feature", "id": f"overture:{identity}",
                                 "geometry": geometry, "properties": row})
                if len(features) > MAX_FEATURES:
                    raise RoadDataError("More than 10,000 road segments matched. Select a smaller AOI.")
    finally:
        reader.close()
    return features


def load_osm_roads(bounds):
    """Read highway ways with original tags; reject partial Overpass results."""
    west, south, east, north = bounds
    query = (f'[out:json][timeout:40];way["highway"]["area"!="yes"]'
             f'({south},{west},{north},{east});out geom;')
    started = time.monotonic()
    try:
        with requests.post(OVERPASS_URL, data={"data": query}, stream=True,
                           headers={"User-Agent": "PetProject/0.1 (local AOI road explorer)"},
                           timeout=(10, 50)) as response:
            response.raise_for_status()
            content = bytearray()
            for chunk in response.iter_content(64 * 1024):
                content.extend(chunk)
                if len(content) > MAX_BYTES or time.monotonic() - started > 60:
                    raise RoadDataError("OSM road response exceeded its limit. Use a smaller AOI or retry later.")
        payload = json.loads(content)
    except (requests.RequestException, ValueError) as error:
        raise RoadDataError("OSM roads could not be loaded. The Overpass service may be busy; retry later.") from error
    if not isinstance(payload, dict) or payload.get("remark") or not isinstance(payload.get("elements"), list):
        raise RoadDataError("OSM returned an incomplete road query. No partial OSM result was saved.")
    if len(payload["elements"]) > MAX_FEATURES:
        raise RoadDataError("Too many OSM roads. Select a smaller AOI.")
    features = []
    for way in payload["elements"]:
        if not isinstance(way, dict) or not isinstance(way.get("tags", {}), dict):
            raise RoadDataError("OSM returned an invalid road record. No partial OSM result was saved.")
        tags = way.get("tags", {})
        if way.get("type") != "way" or not tags.get("highway") or tags.get("area") == "yes":
            continue
        try:
            coordinates = [[point["lon"], point["lat"]] for point in way["geometry"]]
            if len(coordinates) < 2:
                raise ValueError("Incomplete way")
            features.append({"type": "Feature", "id": f"osm:way/{way['id']}",
                             "geometry": {"type": "LineString", "coordinates": coordinates},
                             "properties": {"tags": tags, "class": tags["highway"], "names": {"primary": tags.get("name")}}})
        except (KeyError, TypeError, ValueError) as error:
            raise RoadDataError("OSM returned incomplete road geometry. No partial OSM result was saved.") from error
    return features


if __name__ == "__main__":
    if len(sys.argv) != 4 or sys.argv[1] != "--overture-worker":
        raise SystemExit("This module is used by the road analysis service.")
    try:
        result = {"features": _read_overture(json.loads(sys.argv[2]))}
        serialized = json.dumps(result, allow_nan=False)
        if len(serialized.encode("utf-8")) > MAX_BYTES:
            result = {"error": "Road data exceeds the display limit. Select a smaller AOI."}
    except RoadDataError as error:
        result = {"error": str(error)}
    except ImportError:
        result = {"error": "Road dependencies are missing. Install requirements.txt with the Python environment running Streamlit."}
    except Exception:
        result = {"error": "Overture road data could not be read completely. Check your connection and retry."}
    Path(sys.argv[3]).write_text(json.dumps(result, allow_nan=False), encoding="utf-8")
