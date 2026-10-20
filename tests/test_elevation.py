"""FABDEM range access, raster statistics/artifacts, and UI isolation."""

from contextlib import contextmanager
from copy import deepcopy
import io
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import MagicMock, patch
import zipfile

import numpy as np
import rasterio
from rasterio.io import MemoryFile
from rasterio.transform import from_origin
import requests
from shapely.geometry import box, mapping
from streamlit.testing.v1 import AppTest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from geoanalysis.analysis.elevation import analyze_elevation, find_elevation, summarize_raster
from geoanalysis.services.elevation import ElevationDataError, RangeBudget, fabdem_tiles, tile_sources
from geoanalysis.ui.elevation import elevation_overlays

APP = str(Path(__file__).resolve().parents[1] / "src/geoanalysis/ui/app.py")
RES = 1 / 3600


def collection(polygon):
    return {"type": "FeatureCollection", "features": [
        {"type": "Feature", "geometry": json.loads(json.dumps(mapping(polygon))), "properties": {}}]}


def raster_bytes(values, transform=None, crs="EPSG:4326"):
    with MemoryFile() as memory:
        with memory.open(driver="GTiff", height=values.shape[0], width=values.shape[1], count=1,
                         dtype="float32", transform=transform or from_origin(0, 3 * RES, RES, RES),
                         crs=crs, nodata=-9999) as dataset:
            dataset.write(values.astype("float32"), 1)
        return memory.read()


@contextmanager
def source_fixture(sources):
    content = raster_bytes(np.arange(1, 10).reshape(3, 3))
    yield lambda source: content


def analyzed_fixture():
    aoi = collection(box(0, 0, 3 * RES, 3 * RES))
    with patch("geoanalysis.analysis.elevation.tile_sources", return_value=[{"url": "test", "member": "test.tif"}]), \
         patch("geoanalysis.analysis.elevation.fabdem_tiles", side_effect=source_fixture):
        return analyze_elevation(aoi)


class ElevationRasterTests(unittest.TestCase):
    def test_statistics_nodata_holes_overlap_and_no_samples(self):
        data = np.array([[1, 2, 3], [4, -9999, 6], [7, 8, 9]], dtype="float32")
        transform = from_origin(0, 3, 1, 1)
        _, stats = summarize_raster(data, transform, box(0, 0, 3, 3))
        self.assertEqual(stats["mean_m"], 5)
        self.assertEqual(stats["median_m"], 5)
        self.assertEqual(stats["relief_m"], 8)
        self.assertEqual(stats["nodata_pixels"], 1)
        self.assertAlmostEqual(stats["coverage_percent"], 800 / 9)
        clipped, stats = summarize_raster(data, transform, box(0, 0, 3, 3).difference(box(1, 1, 2, 2)))
        self.assertEqual(stats["selected_pixels"], 8)
        self.assertEqual(stats["nodata_pixels"], 0)
        self.assertEqual(clipped[1, 1], -9999)
        for polygon in [box(0.01, 0.01, 0.1, 0.1), box(1, 1, 2, 2)]:
            with self.assertRaises(ElevationDataError):
                summarize_raster(data, transform, polygon)
        data[0, 0] = np.nan
        _, stats = summarize_raster(data, transform, box(0, 0, 3, 3))
        self.assertEqual(stats["nodata_pixels"], 2)

    def test_complete_artifacts_native_grid_metadata_and_preview(self):
        result = analyzed_fixture()
        stats = result["summary"]["statistics"]
        self.assertEqual(stats["valid_pixels"], 9)
        self.assertEqual(stats["minimum_m"], 1)
        self.assertEqual(stats["maximum_m"], 9)
        self.assertEqual(stats["mean_m"], 5)
        with MemoryFile(result["geotiff"]) as memory, memory.open() as dataset:
            self.assertEqual(dataset.crs.to_epsg(), 4326)
            self.assertAlmostEqual(dataset.res[0], RES)
            self.assertEqual(dataset.nodata, -9999)
            self.assertIn("by-nc-sa", dataset.tags()["LICENSE"])
            self.assertIn("EGM2008", dataset.tags()["VERTICAL_DATUM"])
            self.assertEqual(dataset.read(1).max(), 9)
        self.assertTrue(result["preview_png"].startswith(b"\x89PNG"))
        self.assertEqual(len(result["summary"]["overlay_bounds"]), 2)
        self.assertEqual(len(elevation_overlays(result)), 1)
        self.assertEqual(elevation_overlays(result, visible=False), [])

    def test_mosaic_cross_tile_aoi_and_wrong_crs(self):
        values = np.ones((3, 3), dtype="float32")
        contents = {"a": raster_bytes(values),
                    "b": raster_bytes(values * 2, from_origin(3 * RES, 3 * RES, RES, RES))}
        @contextmanager
        def tiles(sources):
            yield lambda source: contents[source["member"]]
        aoi = collection(box(0, 0, 6 * RES, 3 * RES))
        aoi["features"].append(deepcopy(aoi["features"][0]))
        with patch("geoanalysis.analysis.elevation.tile_sources", return_value=[{"member": "a"}, {"member": "b"}]), \
             patch("geoanalysis.analysis.elevation.fabdem_tiles", side_effect=tiles):
            result = analyze_elevation(aoi)
            self.assertEqual(result["summary"]["statistics"]["valid_pixels"], 18)
            self.assertEqual(result["summary"]["statistics"]["mean_m"], 1.5)
            contents["b"] = raster_bytes(values, crs="EPSG:3857")
            with self.assertRaises(ElevationDataError):
                analyze_elevation(aoi)

    def test_empty_large_polar_aoi_and_hard_deadline(self):
        with patch("geoanalysis.analysis.elevation.subprocess.run") as process:
            for aoi in ({"type": "FeatureCollection", "features": []}, collection(box(0, 0, 1, 1)),
                        collection(box(0, 86, 0.01, 86.01))):
                with self.assertRaises(ValueError):
                    find_elevation(aoi)
            process.assert_not_called()
            process.side_effect = subprocess.TimeoutExpired("worker", 180)
            with self.assertRaisesRegex(ElevationDataError, "three minutes"):
                find_elevation(collection(box(0.01, 0.01, 0.02, 0.02)))


class ElevationSourceTests(unittest.TestCase):
    def test_tile_resolution_worldwide_and_seams(self):
        sources = tile_sources((-89.402, 43.070, -89.395, 43.075))
        self.assertEqual(len(sources), 1)
        self.assertEqual(sources[0]["member"], "N43W090_FABDEM_V1-2.tif")
        self.assertIn("N40W090-N50W080", sources[0]["url"])
        southern = tile_sources((145.1, -37.8, 145.11, -37.79))[0]
        self.assertEqual(southern["member"], "S38E145_FABDEM_V1-2.tif")
        self.assertIn("S40E140-S30E150", southern["url"])
        self.assertIn("N00E170-N10W180", tile_sources((179.1, 1.1, 179.11, 1.11))[0]["url"])
        self.assertEqual(len(tile_sources((0.999, 0.999, 1.001, 1.001))), 4)

    def test_range_validation_rejects_full_download_truncation_and_network_error(self):
        response = MagicMock()
        response.__enter__.return_value = response
        response.status_code = 206
        response.headers = {"Content-Range": "bytes 0-3/1000"}
        response.iter_content.return_value = [b"test"]
        budget = RangeBudget()
        with patch.object(budget.session, "get", return_value=response):
            self.assertEqual(budget.fetch("https://example.org", 0, 3), (b"test", 1000))
            response.status_code = 200
            with self.assertRaisesRegex(ElevationDataError, "byte range"):
                budget.fetch("https://example.org", 0, 3)
            response.status_code = 206
            response.iter_content.return_value = [b"t"]
            with self.assertRaisesRegex(ElevationDataError, "incomplete"):
                budget.fetch("https://example.org", 0, 3)
        with patch.object(budget.session, "get", side_effect=requests.Timeout), self.assertRaises(ElevationDataError):
            budget.fetch("https://example.org", 0, 3)
        with patch("geoanalysis.services.elevation.MAX_DOWNLOAD_BYTES", 1), self.assertRaises(ElevationDataError):
            budget.fetch("https://example.org", 0, 3)
        budget.session.close()

    def test_zip_member_range_read_missing_corrupt_and_size_limit(self):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w") as archive:
            archive.writestr("subfolder/tile.tif", b"raster-content")
        content = stream.getvalue()
        def fetch(budget, url, start, end, total=None):
            return content[start:end + 1], len(content)
        with patch.object(RangeBudget, "fetch", fetch):
            with fabdem_tiles([{}]) as read_tile:
                self.assertEqual(read_tile({"url": "test", "member": "tile.tif"}), b"raster-content")
            with self.assertRaises(ElevationDataError), fabdem_tiles([{}]) as read_tile:
                read_tile({"url": "test", "member": "missing.tif"})
            with patch("geoanalysis.services.elevation.MAX_TILE_BYTES", 1), self.assertRaises(ElevationDataError), fabdem_tiles([{}]) as read_tile:
                read_tile({"url": "test", "member": "tile.tif"})
            content = b"not a zip"
            with self.assertRaises(ElevationDataError), fabdem_tiles([{}]) as read_tile:
                read_tile({"url": "test", "member": "tile.tif"})


class ElevationUITests(unittest.TestCase):
    def test_load_toggle_failure_and_aoi_invalidation_preserve_other_work(self):
        aoi = collection(box(0.01, 0.01, 0.02, 0.02))["features"]
        with patch("streamlit_folium.st_folium", return_value={"all_drawings": aoi}) as component, \
             patch("geoanalysis.ui.elevation.find_elevation", return_value=analyzed_fixture()) as load:
            app = AppTest.from_file(APP).run()
            component.return_value = {"all_drawings": None}
            app.session_state.map_center = [0.015, 0.015]
            app.session_state.map_zoom = 16
            building = {**deepcopy(aoi[0]), "id": "manual", "properties": {"origin": "manual", "status": "planned"}}
            app.session_state.building_review = [building]
            pathways = [{"type": "Feature", "id": "path", "geometry": {"type": "LineString", "coordinates": [[0.012, 0.012], [0.018, 0.018]]},
                         "properties": {"origin": "manual", "role": "pathway", "status": "planned", "length_m": 100}}]
            app.session_state.pathway_review = pathways
            aoi_key = json.dumps([f["geometry"] for f in aoi], sort_keys=True)
            roads = {"aoi_key": aoi_key, "count": 0, "length_m": 0, "release": "2026-09-23.1",
                     "warnings": [], "overture": {"type": "FeatureCollection", "features": []}, "osm": None}
            osm_buildings = {"aoi_key": aoi_key, "count": 0, "geojson": {"type": "FeatureCollection", "features": []}}
            app.session_state.road_result = roads
            app.session_state.osm_building_result = osm_buildings
            app.run()
            next(b for b in app.button if b.label == "Run FABDEM elevation analysis").click().run()
            self.assertFalse(app.exception)
            self.assertEqual(app.session_state.building_review, [building])
            self.assertEqual(app.session_state.pathway_review, pathways)
            self.assertEqual(app.session_state.road_result, roads)
            self.assertEqual(app.session_state.osm_building_result, osm_buildings)
            self.assertEqual(app.session_state.drawings, aoi)
            self.assertEqual(app.session_state.map_center, [0.015, 0.015])
            self.assertEqual(app.session_state.map_zoom, 16)
            next(c for c in app.checkbox if c.label == "Show FABDEM elevation").uncheck().run()
            app.slider[0].set_value(0.4).run()
            next(s for s in app.selectbox if s.label == "Contour interval").select("5 m").run()
            self.assertFalse(app.exception)
            self.assertEqual(load.call_count, 1)
            self.assertTrue(any("5 m contours" in c.value for c in app.caption))
            self.assertEqual(app.session_state.pathway_review, pathways)
            load.side_effect = ElevationDataError("server unavailable")
            next(b for b in app.button if b.label == "Run FABDEM elevation analysis").click().run()
            self.assertIn("elevation_result", app.session_state)
            self.assertTrue(any("last successful elevation" in c.value for c in app.caption))
            component.return_value = {"all_drawings": []}
            app.run()
            self.assertNotIn("elevation_result", app.session_state)
            self.assertNotIn("elevation_error", app.session_state)


if __name__ == "__main__":
    unittest.main()
