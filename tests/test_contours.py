"""Topographic isoline placement, masking, bounds, and map presentation."""

import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import numpy as np
from rasterio.io import MemoryFile
from rasterio.transform import from_origin
from shapely.geometry import box, mapping, shape

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from geoanalysis.analysis.contours import build_contours, contour_interval
from geoanalysis.services.elevation import ElevationDataError
from geoanalysis.ui.app import build_map
from geoanalysis.ui.elevation import elevation_overlays, prepare_topography

RES = 1 / 3600


def raster(values):
    with MemoryFile() as memory:
        with memory.open(driver="GTiff", height=values.shape[0], width=values.shape[1], count=1,
                         dtype="float32", transform=from_origin(0, values.shape[0] * RES, RES, RES),
                         crs="EPSG:4326", nodata=-9999) as src:
            src.write(values.astype("float32"), 1)
        return memory.read()


def collection(polygon):
    return {"type": "FeatureCollection", "features": [
        {"type": "Feature", "geometry": json.loads(json.dumps(mapping(polygon))), "properties": {}}]}


def result():
    return {"geotiff": raster(np.tile(np.arange(12), (12, 1))),
            "summary": {"source": "FABDEM V1-2", "source_url": "https://example.org",
                        "license": "https://creativecommons.org/licenses/by-nc-sa/4.0/",
                        "attribution": "FABDEM", "vertical_datum": "EGM2008"}}


class ContourTests(unittest.TestCase):
    def test_ramp_levels_pixel_center_coordinates_index_and_flat_grid(self):
        contours = build_contours(raster(np.tile(np.arange(12), (12, 1))), interval=2)
        features = contours["features"]
        self.assertTrue(features)
        for feature in features:
            level = feature["properties"]["elevation_m"]
            self.assertEqual(level % 2, 0)
            self.assertEqual(feature["properties"]["index"], level % 10 == 0)
            for x, y in feature["geometry"]["coordinates"]:
                self.assertAlmostEqual(x, (level + 0.5) * RES)
                self.assertGreaterEqual(y, RES / 2 - 1e-12)
        self.assertEqual(contours["interval_m"], 2)
        self.assertEqual(contours["index_interval_m"], 10)
        flat = build_contours(raster(np.ones((4, 4)) * 100), interval=5)
        self.assertEqual(flat["features"], [])
        self.assertEqual(flat["minimum_m"], 100)
        self.assertEqual(build_contours(raster(np.ones((1, 4))))["features"], [])

    def test_holes_exact_aoi_clip_and_nodata_not_bridged(self):
        values = np.tile(np.arange(12), (12, 1)).astype("float32")
        hole = box(4 * RES, 4 * RES, 8 * RES, 8 * RES)
        aoi = box(RES, RES, 11 * RES, 11 * RES).difference(hole)
        contours = build_contours(raster(values), collection(aoi), 2)
        self.assertTrue(contours["features"])
        for feature in contours["features"]:
            line = shape(feature["geometry"])
            self.assertTrue(aoi.covers(line))
            self.assertFalse(line.relate_pattern(hole, "T********"))
        values[5:7, :] = -9999
        contours = build_contours(raster(values), interval=2)
        for feature in contours["features"]:
            ys = [p[1] for p in feature["geometry"]["coordinates"]]
            self.assertFalse(min(ys) < 5 * RES and max(ys) > 7 * RES)

    def test_invalid_intervals_nodata_and_resource_caps(self):
        content = raster(np.tile(np.arange(12), (12, 1)))
        for spacing in [0, -2, float("inf"), float("nan")]:
            with self.subTest(spacing=spacing), self.assertRaises(ValueError):
                build_contours(content, interval=spacing)
        with self.assertRaises(ElevationDataError):
            build_contours(content, interval=0.01)
        with patch("geoanalysis.analysis.contours.MAX_FEATURES", 0), self.assertRaises(ElevationDataError):
            build_contours(content, interval=2)
        with self.assertRaises(ElevationDataError):
            build_contours(raster(np.ones((4, 4)) * -9999))
        self.assertEqual(contour_interval(260, 279), 2)
        self.assertGreaterEqual(contour_interval(-100, 1900), 1900 / 12)

    def test_existing_raster_cached_interval_changes_legend_labels_and_no_fill(self):
        saved = result()
        with patch("geoanalysis.ui.elevation.build_contours", wraps=build_contours) as contours:
            first = prepare_topography(saved, interval=2)
            self.assertIs(first, prepare_topography(saved, interval=2))
            self.assertEqual(contours.call_count, 1)
            prepare_topography(saved, interval=5)
            self.assertEqual(contours.call_count, 2)
        import streamlit_folium
        calls = []
        with patch("streamlit_folium._component_func", side_effect=lambda **kwargs: calls.append(kwargs) or {}):
            streamlit_folium.st_folium(build_map(), key="map")
            streamlit_folium.st_folium(build_map(), key="map",
                                     feature_group_to_add=elevation_overlays(saved, interval=2))
        self.assertEqual(calls[0]["script"], calls[1]["script"])
        extra = calls[1]["feature_group"]
        self.assertIn("FABDEM topographic map", extra)
        self.assertIn("Contour: 2 m", extra)
        self.assertIn("Index: 10 m", extra)
        self.assertIn("EGM2008", extra)
        self.assertIn(r"\u003e10 m\u003c/div", extra)
        self.assertNotIn("imageOverlay", extra)
        self.assertEqual(elevation_overlays(saved, visible=False), [])


if __name__ == "__main__":
    unittest.main()
