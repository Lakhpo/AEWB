"""Read Microsoft's indexed, gzipped GeoJSONL footprint release.

No user boundary is uploaded: the index selects partition URLs, then Python
filters their contents locally. Large files are spooled to temporary storage.
"""

import csv
from functools import lru_cache
import gzip
import io
import json
import math
import tempfile
import time
from urllib.parse import urlparse

import requests
from shapely.geometry import box

RELEASE = "2026-08-13"
INDEX_URL = f"https://bfppub.blob.core.windows.net/%24web/{RELEASE}/dataset-links.csv"
SOURCE_URL = "https://github.com/microsoft/GlobalMLBuildingFootprints"
MAX_PARTITIONS = 4
MAX_DOWNLOAD_BYTES = 100 * 1024 * 1024
MAX_EXPANDED_BYTES = 1024 * 1024 * 1024
MAX_SECONDS = 180


class BuildingDataError(RuntimeError):
    """The source cannot supply a complete result for this request."""


def quadkey_bounds(quadkey):
    """Decode a Bing quadkey to west, south, east, north in WGS 84."""
    if not quadkey or any(d not in "0123" for d in quadkey):
        raise BuildingDataError("Microsoft's index contains an invalid tile key.")
    x = y = 0
    for digit in quadkey:
        x = x * 2 + (int(digit) & 1)
        y = y * 2 + (int(digit) >> 1)
    n = 2 ** len(quadkey)
    latitude = lambda row: math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * row / n))))
    return x / n * 360 - 180, latitude(y + 1), (x + 1) / n * 360 - 180, latitude(y)


@lru_cache(maxsize=1)
def load_index():
    """Cache the immutable release index in memory, not individual AOIs."""
    try:
        with requests.get(INDEX_URL, timeout=(10, 30)) as response:
            response.raise_for_status()
            rows = list(csv.DictReader(io.StringIO(response.text)))
    except requests.RequestException as error:
        raise BuildingDataError("Could not load Microsoft's building index. Check your connection and retry.") from error
    if not rows or not {"QuadKey", "Url", "Location"}.issubset(rows[0]):
        raise BuildingDataError("Microsoft's building index has an unexpected format.")
    return rows


def select_partitions(aoi, rows):
    """Find indexed tiles near the AOI, with a border cushion for footprints.

    The small geographic padding is a lookup margin, not an area calculation.
    It includes neighboring shards close to tile edges; source coverage still
    cannot be assumed complete.
    """
    search_bounds = box(*aoi.bounds).buffer(0.002)
    selected = []
    seen = set()
    for row in rows:
        if row["Url"] not in seen and search_bounds.intersects(box(*quadkey_bounds(row["QuadKey"]))):
            selected.append(row)
            seen.add(row["Url"])
    if not selected:
        raise BuildingDataError("No Microsoft footprint partitions cover this AOI. This is a coverage gap, not a zero-building result.")
    if len(selected) > MAX_PARTITIONS:
        raise BuildingDataError("This area needs too many source files. Select a smaller, local AOI and retry.")
    return selected


def iter_footprints(partitions, progress=None):
    """Yield records after bounded downloads; never present partial totals."""
    downloaded = expanded = 0
    started = time.monotonic()
    try:
        for index, partition in enumerate(partitions, start=1):
            if progress:
                progress(f"Reading Microsoft footprint file {index} of {len(partitions)}…")
            url = partition["Url"]
            parsed = urlparse(url)
            if parsed.scheme != "https" or parsed.hostname not in {
                "bfppub.blob.core.windows.net", "bfppub.z5.web.core.windows.net",
            }:
                raise BuildingDataError("Microsoft's index contains an unsupported data host.")
            with tempfile.TemporaryFile() as compressed:
                with requests.get(url, stream=True, timeout=(10, 30)) as response:
                    response.raise_for_status()
                    for chunk in response.iter_content(chunk_size=256 * 1024):
                        downloaded += len(chunk)
                        if downloaded > MAX_DOWNLOAD_BYTES or time.monotonic() - started > MAX_SECONDS:
                            raise BuildingDataError("Source download exceeded the local analysis limit. Try a smaller AOI or another location.")
                        compressed.write(chunk)
                compressed.seek(0)
                with gzip.GzipFile(fileobj=compressed) as records:
                    while line := records.readline(1024 * 1024 + 1):
                        expanded += len(line)
                        if len(line) > 1024 * 1024 or expanded > MAX_EXPANDED_BYTES or time.monotonic() - started > MAX_SECONDS:
                            raise BuildingDataError("Source processing exceeded the local analysis limit. No partial count was returned.")
                        if line.strip():
                            yield json.loads(line)
    except (requests.RequestException, OSError, EOFError, ValueError) as error:
        raise BuildingDataError("A Microsoft footprint file could not be read completely. Check your connection and retry.") from error
