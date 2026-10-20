"""Bounded access to official FABDEM V1-2 ZIP members via HTTP ranges."""

from contextlib import contextmanager
import io
import math
import re
import time
import zipfile

import requests

BASE_URL = "https://data.bris.ac.uk/datasets/s5hqmjcdj8yo2ibzi9b4ew3sn/"
SOURCE_URL = "https://doi.org/10.5523/bris.s5hqmjcdj8yo2ibzi9b4ew3sn"
LICENSE = "https://creativecommons.org/licenses/by-nc-sa/4.0/"
RELEASE = "FABDEM V1-2"
ATTRIBUTION = (
    "Hawker, L., Uhe, P., Paulo, L., Sosa, J., Savage, J., Sampson, C., & Neal, J. (2022). "
    "A 30 m global map of elevation with forests and buildings removed. Environmental Research Letters, 17(2), 024016. "
    "FABDEM is produced using Copernicus WorldDEM-30 © DLR e.V. 2010-2014 and © Airbus Defence and Space GmbH "
    "2014-2018 provided under COPERNICUS by the European Union and ESA; all rights reserved. "
    "The organisations in charge of the Copernicus programme by law or by delegation do not incur any liability "
    "for any use of the Copernicus WorldDEM-30."
)
MAX_DOWNLOAD_BYTES = 256 * 1024 * 1024
MAX_TILE_BYTES = 80 * 1024 * 1024
MAX_SECONDS = 180


class ElevationDataError(RuntimeError):
    """Terrain data could not supply a complete, trustworthy AOI result."""


def tile_label(latitude, longitude):
    # The provider wraps the NE corner of 170E bundles to W180.
    longitude = -180 if longitude == 180 else longitude
    return f"{'N' if latitude >= 0 else 'S'}{abs(latitude):02d}{'E' if longitude >= 0 else 'W'}{abs(longitude):03d}"


def tile_sources(bounds):
    """Resolve 1-degree land tiles and their 10-degree official archives."""
    west, south, east, north = bounds
    # Point-registered rasters extend half a cell beyond nominal tile bounds.
    margin = 1 / 7200
    sources = []
    for lat in range(max(-90, math.floor(south - margin)), min(90, math.ceil(north + margin))):
        for lon in range(max(-180, math.floor(west - margin)), min(180, math.ceil(east + margin))):
            block_lat, block_lon = 10 * (lat // 10), 10 * (lon // 10)
            block = f"{tile_label(block_lat, block_lon)}-{tile_label(block_lat + 10, block_lon + 10)}_FABDEM_V1-2"
            sources.append({"url": f"{BASE_URL}{block}.zip", "member": f"{tile_label(lat, lon)}_FABDEM_V1-2.tif"})
    if not sources or len(sources) > 4:
        raise ElevationDataError("Elevation analysis supports at most four FABDEM tiles. Select a smaller AOI.")
    return sources


class RangeBudget:
    """One byte/time budget shared across all archives in an analysis."""

    def __init__(self):
        self.started = time.monotonic()
        self.downloaded = 0
        self.session = requests.Session()

    def fetch(self, url, start, end, total=None):
        if time.monotonic() - self.started > MAX_SECONDS:
            raise ElevationDataError("FABDEM loading timed out. Retry later or choose a smaller AOI.")
        expected = end - start + 1
        if expected > MAX_TILE_BYTES or self.downloaded + expected > MAX_DOWNLOAD_BYTES:
            raise ElevationDataError("FABDEM download exceeds the local limit. Select a smaller AOI.")
        try:
            with self.session.get(url, headers={"Range": f"bytes={start}-{end}", "Accept-Encoding": "identity",
                                                "User-Agent": "PetProject/0.1 (local terrain analysis)"},
                                  stream=True, timeout=(10, 30)) as response:
                if response.status_code == 404:
                    raise ElevationDataError("FABDEM has no published archive for part of this AOI. Coverage may be unavailable.")
                response.raise_for_status()
                match = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+)", response.headers.get("Content-Range", ""))
                if (response.status_code != 206 or not match or tuple(map(int, match.groups()[:2])) != (start, end)
                        or (total is not None and int(match[3]) != total)):
                    raise ElevationDataError("FABDEM did not return the requested byte range. No full archive was downloaded; retry later.")
                content = bytearray()
                for chunk in response.iter_content(256 * 1024):
                    content.extend(chunk)
                    self.downloaded += len(chunk)
                    if (len(content) > expected or self.downloaded > MAX_DOWNLOAD_BYTES
                            or time.monotonic() - self.started > MAX_SECONDS):
                        raise ElevationDataError("FABDEM response exceeded its time or size limit. No partial result was saved.")
                if len(content) != expected:
                    raise ElevationDataError("FABDEM returned an incomplete byte range. Retry loading elevation.")
                return bytes(content), int(match[3])
        except requests.RequestException as error:
            raise ElevationDataError("FABDEM could not be reached. Check your connection or retry when the Bristol data server is available.") from error


class RemoteArchive(io.RawIOBase):
    """Seekable range reader for zipfile; never reads an entire regional ZIP."""

    def __init__(self, url, budget):
        self.url, self.budget, self.position = url, budget, 0
        _, self.size = budget.fetch(url, 0, 0)

    def seekable(self):
        return True

    def readable(self):
        return True

    def tell(self):
        return self.position

    def seek(self, offset, whence=0):
        position = offset if whence == 0 else self.position + offset if whence == 1 else self.size + offset
        if position < 0:
            raise ValueError("Invalid archive seek")
        self.position = position
        return position

    def read(self, size=-1):
        size = min(self.size - self.position, size if size >= 0 else self.size - self.position)
        if size <= 0:
            return b""
        content, _ = self.budget.fetch(self.url, self.position, self.position + size - 1, self.size)
        self.position += size
        return content


@contextmanager
def fabdem_tiles(sources):
    """Yield bounded in-memory tile bytes without extracting files to disk."""
    budget = RangeBudget()
    archives = {}
    try:
        def read_tile(source):
            url = source["url"]
            if url not in archives:
                archives[url] = zipfile.ZipFile(RemoteArchive(url, budget))
            archive = archives[url]
            matches = [info for info in archive.infolist() if info.filename.split("/")[-1] == source["member"]]
            if not matches:
                raise ElevationDataError(f"FABDEM tile {source['member']} is unavailable. No partial terrain result was saved.")
            if len(matches) != 1 or matches[0].file_size > MAX_TILE_BYTES or matches[0].compress_size > MAX_TILE_BYTES:
                raise ElevationDataError("FABDEM returned an ambiguous or oversized elevation tile.")
            with archive.open(matches[0]) as member:
                content = member.read(MAX_TILE_BYTES + 1)
            if len(content) > MAX_TILE_BYTES:
                raise ElevationDataError("FABDEM tile exceeded its expanded-size limit.")
            return content
        yield read_tile
    except (OSError, ValueError, zipfile.BadZipFile, EOFError, NotImplementedError) as error:
        raise ElevationDataError("FABDEM archive could not be read completely. No partial result was saved.") from error
    finally:
        for archive in archives.values():
            archive.close()
        budget.session.close()
