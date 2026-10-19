"""Spatial selection, source errors, and bounded data access tests."""

import gzip
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import MagicMock, patch

import requests
from shapely.geometry import box, mapping

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from geoanalysis.analysis.analysis import find_buildings
from geoanalysis.services.buildings import BuildingDataError, iter_footprints, quadkey_bounds, select_partitions


def feature(geometry):
    return {"type": "Feature", "geometry": json.loads(json.dumps(mapping(geometry))), "properties": {}}


class AnalysisTests(unittest.TestCase):
    def setUp(self):
        self.aoi = {"type": "FeatureCollection", "features": [feature(box(0, 0, 0.1, 0.1))]}

    def run_with(self, records):
        with patch("geoanalysis.analysis.analysis.load_index", return_value=[]), \
             patch("geoanalysis.analysis.analysis.select_partitions", return_value=[{}]), \
             patch("geoanalysis.analysis.analysis.iter_footprints", return_value=iter(records)):
            return find_buildings(self.aoi)

    def test_inside_crossing_touch_outside_and_duplicate(self):
        inside = feature(box(0.01, 0.01, 0.02, 0.02))
        crossing = feature(box(0.09, 0.09, 0.11, 0.11))
        touching = feature(box(0.1, 0.01, 0.11, 0.02))
        outside = feature(box(0.2, 0.2, 0.3, 0.3))
        self.aoi["features"].append(feature(box(0, 0, 0.05, 0.05)))
        result = self.run_with([inside, crossing, touching, outside, inside])
        self.assertEqual(result["count"], 2)
        self.assertEqual(len(result["geojson"]["features"]), 2)
        self.assertEqual(result["geojson"]["features"][1]["geometry"], crossing["geometry"])

    def test_hole_is_excluded_and_invalid_source_is_reported(self):
        self.aoi["features"] = [feature(box(0, 0, 0.1, 0.1).difference(box(0.02, 0.02, 0.08, 0.08)))]
        result = self.run_with([feature(box(0.03, 0.03, 0.04, 0.04)), {"geometry": None}])
        self.assertEqual(result["count"], 0)
        self.assertEqual(result["skipped"], 1)

    def test_oversized_and_empty_aoi_fail_before_network_access(self):
        with patch("geoanalysis.analysis.analysis.load_index") as network:
            for collection in [
                {"type": "FeatureCollection", "features": []},
                {"type": "FeatureCollection", "features": [feature(box(0, 0, 2, 2))]},
            ]:
                with self.assertRaises(ValueError):
                    find_buildings(collection)
            network.assert_not_called()

    def test_result_limit_returns_no_partial_count(self):
        with patch("geoanalysis.analysis.analysis.MAX_BUILDINGS", 1), self.assertRaises(BuildingDataError):
            self.run_with([feature(box(0.01, 0.01, 0.02, 0.02)), feature(box(0.03, 0.03, 0.04, 0.04))])

    def test_source_failure_is_not_a_zero_result(self):
        def broken(*args):
            yield feature(box(0.01, 0.01, 0.02, 0.02))
            raise BuildingDataError("Connection interrupted")
        with patch("geoanalysis.analysis.analysis.load_index", return_value=[]), \
             patch("geoanalysis.analysis.analysis.select_partitions", return_value=[{}]), \
             patch("geoanalysis.analysis.analysis.iter_footprints", side_effect=broken), \
             self.assertRaises(BuildingDataError):
            find_buildings(self.aoi)


class SourceTests(unittest.TestCase):
    def test_quadkey_bounds_and_missing_coverage(self):
        self.assertEqual(quadkey_bounds("0")[:3], (-180.0, 0.0, 0.0))
        self.assertAlmostEqual(quadkey_bounds("0")[3], 85.05112878)
        row = {"QuadKey": "0", "Url": "https://example.org/a"}
        self.assertEqual(select_partitions(box(-90, 40, -89.9, 40.1), [row]), [row])
        with self.assertRaises(BuildingDataError):
            select_partitions(box(90, -40, 90.1, -39.9), [row])

    def test_gzip_read_and_download_limit(self):
        record = feature(box(0, 0, 0.01, 0.01))
        payload = gzip.compress((json.dumps(record) + "\n").encode())
        response = MagicMock()
        response.__enter__.return_value = response
        response.iter_content.return_value = [payload]
        partition = [{"Url": "https://bfppub.z5.web.core.windows.net/test.csv.gz"}]
        with patch("geoanalysis.services.buildings.requests.get", return_value=response):
            self.assertEqual(list(iter_footprints(partition)), [record])
            with patch("geoanalysis.services.buildings.MAX_DOWNLOAD_BYTES", 1), self.assertRaises(BuildingDataError):
                list(iter_footprints(partition))

    def test_network_failure_and_corruption_raise_data_errors(self):
        partition = [{"Url": "https://bfppub.z5.web.core.windows.net/test.csv.gz"}]
        with patch("geoanalysis.services.buildings.requests.get", side_effect=requests.Timeout), self.assertRaises(BuildingDataError):
            list(iter_footprints(partition))
        response = MagicMock()
        response.__enter__.return_value = response
        response.iter_content.return_value = [b"not a gzip file"]
        with patch("geoanalysis.services.buildings.requests.get", return_value=response), self.assertRaises(BuildingDataError):
            list(iter_footprints(partition))


if __name__ == "__main__":
    unittest.main()
