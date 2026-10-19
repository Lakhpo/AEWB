"""AOI input validation and export contract tests."""

from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from geoanalysis.core.geometry import aoi_feature_collection, parse_coordinates


def feature(ring):
    return {"type": "Feature", "properties": {},
            "geometry": {"type": "Polygon", "coordinates": [ring]}}


class AOITests(unittest.TestCase):
    def setUp(self):
        self.rectangle = feature([[-100, 39], [-99, 39], [-99, 40], [-100, 40], [-100, 39]])

    def test_export_preserves_longitude_latitude_and_does_not_mutate_input(self):
        original = deepcopy(self.rectangle)
        result = aoi_feature_collection([self.rectangle])
        self.assertEqual(result["type"], "FeatureCollection")
        self.assertEqual(result["features"][0]["geometry"], original["geometry"])
        result["features"][0]["geometry"]["coordinates"][0][0][0] = 0
        self.assertEqual(self.rectangle, original)

    def test_polygon_and_multiple_boundaries(self):
        triangle = feature([[10, 10], [11, 10], [10, 11], [10, 10]])
        self.assertEqual(len(aoi_feature_collection([self.rectangle, triangle])["features"]), 2)

    def test_deleted_selection_is_empty(self):
        self.assertEqual(aoi_feature_collection([])["features"], [])

    def test_rejects_invalid_geometry(self):
        invalid = [
            feature([[0, 0], [1, 1], [0, 1], [1, 0], [0, 0]]),  # crossing
            feature([[0, 0], [1, 0], [2, 0], [0, 0]]),  # zero area
            feature([[0, 0], [1, 0], [1, 1], [0, 1]]),  # open ring
            feature([[181, 0], [182, 0], [182, 1], [181, 0]]),
            feature([[0, 91], [1, 91], [1, 92], [0, 91]]),
            feature([[0, 0], [float("nan"), 1], [1, 0], [0, 0]]),
            feature([[179, 0], [-179, 0], [-179, 1], [179, 0]]),
            {"type": "Feature", "geometry": {"type": "Point", "coordinates": [0, 0]}},
            {"type": "Feature", "geometry": None},
        ]
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(ValueError):
                aoi_feature_collection([self.rectangle, value])


class CoordinateTests(unittest.TestCase):
    def test_decimal_coordinates_keep_latitude_longitude_order(self):
        for value, expected in [
            ("43.0731, -89.4012", (43.0731, -89.4012)),
            ("  -33.8688   151.2093  ", (-33.8688, 151.2093)),
            ("0, 0", (0.0, 0.0)),
            ("90, -180", (90.0, -180.0)),
            ("-90, 180", (-90.0, 180.0)),
        ]:
            with self.subTest(value=value):
                self.assertEqual(parse_coordinates(value), expected)

    def test_invalid_or_ambiguous_coordinates_are_rejected(self):
        for value in ("", "43", "43, -89, 10", "north, west", "NaN, 0", "0, inf",
                      "91, 0", "-91, 0", "0, 181", "0, -181", "43,", "43N, 89W"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_coordinates(value)


if __name__ == "__main__":
    unittest.main()
