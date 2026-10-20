"""OSM footprint reconstruction, completeness, isolation, and UI regressions."""

from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import MagicMock, patch

import requests
from shapely.geometry import box, mapping, shape
from streamlit.testing.v1 import AppTest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from geoanalysis.analysis.osm_buildings import find_osm_buildings
from geoanalysis.services.buildings import BuildingDataError
from geoanalysis.services.osm_buildings import load_osm_buildings, parse_buildings
from geoanalysis.ui.osm_buildings import osm_building_overlays
from geoanalysis.core.building_review import source_buildings

APP = str(Path(__file__).resolve().parents[1] / "src/geoanalysis/ui/app.py")


def way(identity, polygon):
    return {"type": "way", "id": identity, "tags": {"building": "yes", "name": "Test"},
            "geometry": [{"lon": x, "lat": y} for x, y in polygon.exterior.coords]}


def aoi(polygon=box(0, 0, 0.1, 0.1)):
    return {"type": "FeatureCollection", "features": [
        {"type": "Feature", "geometry": json.loads(json.dumps(mapping(polygon))), "properties": {}}]}


def member(identity, coordinates, role="outer"):
    return {"type": "way", "ref": identity, "role": role,
            "geometry": [{"lon": x, "lat": y} for x, y in coordinates]}


class OSMBuildingTests(unittest.TestCase):
    def test_split_reversed_relation_courtyard_and_member_deduplication(self):
        outer = box(0.01, 0.01, 0.09, 0.09)
        coords = list(outer.exterior.coords)
        inner = box(0.03, 0.03, 0.04, 0.04)
        relation = {"type": "relation", "id": 10, "tags": {"building": "yes", "type": "multipolygon"},
                    "members": [member(1, coords[:3]), member(2, list(reversed(coords[2:]))),
                                member(3, list(inner.exterior.coords), "inner")]}
        result = parse_buildings({"elements": [way(1, outer), relation]})
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["id"], "osm:relation/10")
        self.assertTrue(shape(result[0]["geometry"]).equals(outer.difference(inner)))
        relation["members"].append(member(4, list(box(0.12, 0.01, 0.13, 0.02).exterior.coords)))
        result = parse_buildings({"elements": [relation]})
        self.assertEqual(result[0]["geometry"]["type"], "MultiPolygon")

    def test_interior_overlap_full_footprints_duplicates_and_holes(self):
        inside = way(1, box(0.01, 0.01, 0.02, 0.02))
        crossing = way(2, box(0.09, 0.09, 0.11, 0.11))
        touching = way(3, box(0.1, 0.01, 0.11, 0.02))
        in_hole = way(4, box(0.04, 0.04, 0.05, 0.05))
        duplicate = {**inside, "id": 5}
        collection = aoi(box(0, 0, 0.1, 0.1).difference(box(0.03, 0.03, 0.06, 0.06)))
        collection["features"].append(deepcopy(collection["features"][0]))
        with patch("geoanalysis.analysis.osm_buildings.load_osm_buildings",
                   return_value={"elements": [inside, crossing, touching, in_hole, duplicate]}):
            result = find_osm_buildings(collection)
        self.assertEqual(result["count"], 2)
        self.assertEqual(result["geojson"]["features"][1]["geometry"]["coordinates"],
                         json.loads(json.dumps(mapping(box(0.09, 0.09, 0.11, 0.11))))["coordinates"])
        self.assertIn("license", result["geojson"])
        self.assertEqual(result["geojson"]["features"][0]["properties"]["tags"]["name"], "Test")

    def test_invalid_partial_open_and_out_of_range_fail_without_partial_results(self):
        valid = way(1, box(0.01, 0.01, 0.02, 0.02))
        open_way = deepcopy(valid)
        open_way["geometry"].pop()
        relation = {"type": "relation", "id": 1, "tags": {"building": "yes", "type": "multipolygon"},
                    "members": [member(1, [(0, 0), (0, 0.1)])]}
        for payload in ({"remark": "timeout", "elements": [valid]}, {},
                        {"elements": [valid, open_way]}, {"elements": [valid, relation]},
                        {"elements": [way(9, box(181, 0, 182, 1))]}):
            with self.subTest(payload=payload), self.assertRaises(BuildingDataError):
                parse_buildings(payload)

    def test_aoi_validation_before_network_and_worldwide_bounds(self):
        with patch("geoanalysis.analysis.osm_buildings.load_osm_buildings", return_value={"elements": []}) as network:
            for collection in (aoi(box(0, 0, 1, 1)), {"type": "FeatureCollection", "features": []}):
                with self.assertRaises(ValueError):
                    find_osm_buildings(collection)
            network.assert_not_called()
            find_osm_buildings(aoi(box(145, -38, 145.01, -37.99)))
            self.assertEqual(network.call_args.args[0], (145, -38, 145.01, -37.99))

    def test_network_query_order_limits_and_timeout_errors(self):
        response = MagicMock()
        response.__enter__.return_value = response
        response.iter_content.return_value = [b'{"elements":[]}']
        with patch("geoanalysis.services.osm_buildings.requests.post", return_value=response) as post:
            self.assertEqual(load_osm_buildings((145, -38, 145.01, -37.99)), {"elements": []})
            query = post.call_args.kwargs["data"]["data"]
            self.assertIn("(-38,145,-37.99,145.01)", query)
            self.assertIn('relation["type"="multipolygon"]', query)
            self.assertTrue(query.endswith("out geom;"))
            with patch("geoanalysis.services.osm_buildings.MAX_BYTES", 1), self.assertRaises(BuildingDataError):
                load_osm_buildings((0, 0, 0.1, 0.1))
        with patch("geoanalysis.services.osm_buildings.requests.post", side_effect=requests.Timeout), self.assertRaises(BuildingDataError):
            load_osm_buildings((0, 0, 0.1, 0.1))
        with patch("geoanalysis.services.osm_buildings.MAX_ELEMENTS", 0), self.assertRaises(BuildingDataError):
            parse_buildings({"elements": [way(1, box(0, 0, 0.01, 0.01))]})


class OSMBuildingUITests(unittest.TestCase):
    def test_load_toggle_failed_reload_and_aoi_clear_preserve_review_and_view(self):
        drawings = aoi()["features"]
        source = {**aoi(box(0.01, 0.01, 0.02, 0.02))["features"][0], "id": "ms1"}
        result = {"count": 1, "geojson": {"type": "FeatureCollection", "features": [source]}}
        with patch("streamlit_folium.st_folium", return_value={"all_drawings": drawings}) as component, \
             patch("geoanalysis.ui.osm_buildings.find_osm_buildings", return_value=result) as load:
            app = AppTest.from_file(APP).run()
            component.return_value = {"all_drawings": None}
            app.session_state.building_review = source_buildings([source])
            app.session_state.map_center = [43.07, -89.4]
            app.session_state.map_zoom = 17
            aoi_key = json.dumps([f["geometry"] for f in drawings], sort_keys=True)
            microsoft = {**deepcopy(result), "aoi_key": aoi_key, "release": "2026-08-13", "skipped": 0}
            roads = {"aoi_key": aoi_key, "count": 0, "length_m": 0, "release": "2026-09-23.1",
                     "warnings": [], "overture": {"type": "FeatureCollection", "features": []}, "osm": None}
            app.session_state.building_result = microsoft
            app.session_state.road_result = roads
            app.run()
            before = deepcopy(app.session_state.building_review)
            next(b for b in app.button if b.label == "Load OSM buildings").click().run()
            self.assertFalse(app.exception)
            self.assertEqual(app.session_state.building_review, before)
            self.assertEqual(app.session_state.map_center, [43.07, -89.4])
            self.assertEqual(app.session_state.map_zoom, 17)
            self.assertEqual(app.session_state.building_result, microsoft)
            self.assertEqual(app.session_state.road_result, roads)
            self.assertEqual(app.session_state.osm_building_result["count"], 1)
            self.assertEqual(len(osm_building_overlays(result)), 1)
            self.assertEqual(osm_building_overlays(result, visible=False), [])
            next(c for c in app.checkbox if c.label == "Show OSM buildings").uncheck().run()
            self.assertEqual(app.session_state.building_review, before)
            load.side_effect = BuildingDataError("busy")
            next(b for b in app.button if b.label == "Load OSM buildings").click().run()
            self.assertFalse(app.exception)
            self.assertEqual(app.session_state.osm_building_result["count"], 1)
            self.assertTrue(any("last successful OSM" in c.value for c in app.caption))
            component.return_value = {"all_drawings": aoi(box(0, 0, 0.05, 0.05))["features"]}
            app.run()
            self.assertNotIn("osm_building_result", app.session_state)
            self.assertNotIn("osm_building_error", app.session_state)


if __name__ == "__main__":
    unittest.main()
