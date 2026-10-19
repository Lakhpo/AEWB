"""Road geometry, source failure, and workspace regression checks."""

from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

from streamlit.testing.v1 import AppTest
import streamlit_folium

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from geoanalysis.analysis.roads import find_roads
from geoanalysis.services import roads as source
from geoanalysis.services.roads import RoadDataError
from geoanalysis.ui.app import build_map
from geoanalysis.ui.roads import road_overlays

APP = str(Path(__file__).resolve().parents[1] / "src/geoanalysis/ui/app.py")
AOI = {"type": "Feature", "properties": {}, "geometry": {"type": "Polygon", "coordinates": [
    [[-89, 43], [-88.98, 43], [-88.98, 43.02], [-89, 43.02], [-89, 43]],
]}}
COLLECTION = {"type": "FeatureCollection", "features": [AOI]}


def road(identity="one", coordinates=None):
    return {"type": "Feature", "id": identity, "geometry": {"type": "LineString", "coordinates":
            coordinates or [[-89.01, 43.01], [-88.97, 43.01]]},
            "properties": {"names": {"primary": "Main Street"}, "class": "residential",
                           "access_restrictions": [{"access_type": "denied", "between": [0.2, 0.4]}]}}


class RoadAnalysisTests(unittest.TestCase):
    def test_clip_deduplicate_boundary_contacts_and_separate_sources(self):
        inside = road()
        boundary = road("edge", [[-89, 43], [-88.98, 43]])
        point = road("touch", [[-89.01, 42.99], [-89, 43]])
        original = deepcopy(inside)
        with patch("geoanalysis.analysis.roads.load_overture_roads", return_value=[inside, inside, boundary, point]), \
             patch("geoanalysis.analysis.roads.load_osm_roads", return_value=[road("osm")]):
            result = find_roads(COLLECTION, include_osm=True)
        self.assertEqual(result["count"], 1)
        self.assertEqual(len(result["osm"]["features"]), 1)
        self.assertAlmostEqual(result["length_m"], 1630.6, delta=10)
        feature = result["overture"]["features"][0]
        self.assertEqual(list(feature["geometry"]["coordinates"][0]), [-89, 43.01])
        self.assertEqual(feature["properties"]["access_restrictions"], inside["properties"]["access_restrictions"])
        self.assertIn("original source", feature["properties"]["access_scope"])
        self.assertEqual(inside, original)
        json.dumps(result, allow_nan=False)

    def test_holes_split_clipped_roads(self):
        collection = deepcopy(COLLECTION)
        collection["features"][0]["geometry"]["coordinates"].append(
            [[-88.995, 43.005], [-88.985, 43.005], [-88.985, 43.015], [-88.995, 43.015], [-88.995, 43.005]])
        with patch("geoanalysis.analysis.roads.load_overture_roads", return_value=[road()]):
            result = find_roads(collection)
        self.assertEqual(result["overture"]["features"][0]["geometry"]["type"], "MultiLineString")
        self.assertAlmostEqual(result["length_m"], 815.3, delta=5)

    def test_optional_osm_failure_keeps_overture_and_primary_failure_raises(self):
        with patch("geoanalysis.analysis.roads.load_overture_roads", return_value=[road()]), \
             patch("geoanalysis.analysis.roads.load_osm_roads", side_effect=RoadDataError("Busy")):
            result = find_roads(COLLECTION, include_osm=True)
        self.assertEqual(result["count"], 1)
        self.assertIsNone(result["osm"])
        self.assertIn("Busy", result["warnings"][0])
        with patch("geoanalysis.analysis.roads.load_overture_roads", side_effect=RoadDataError("Offline")):
            with self.assertRaisesRegex(RoadDataError, "Offline"):
                find_roads(COLLECTION)

    def test_empty_oversized_and_invalid_aoi_fail_before_network(self):
        oversized = deepcopy(COLLECTION)
        oversized["features"][0]["geometry"]["coordinates"][0][1][0] = -88
        with patch("geoanalysis.analysis.roads.load_overture_roads") as load:
            for selection in ({}, {"type": "FeatureCollection", "features": []}, oversized):
                with self.assertRaises(ValueError):
                    find_roads(selection)
            load.assert_not_called()

    def test_non_us_aoi_is_sent_to_sources_without_country_filter(self):
        collection = deepcopy(COLLECTION)
        collection["features"][0]["geometry"]["coordinates"] = [[
            [2.29, 48.85], [2.30, 48.85], [2.30, 48.86], [2.29, 48.86], [2.29, 48.85]]]
        with patch("geoanalysis.analysis.roads.load_overture_roads", return_value=[]) as load:
            result = find_roads(collection)
        load.assert_called_once_with((2.29, 48.85, 2.3, 48.86))
        self.assertEqual(result["count"], 0)

    def test_malformed_source_geometry_is_an_actionable_failure(self):
        invalid = road()
        invalid["geometry"] = {"type": "LineString", "coordinates": [[-89, 43]]}
        with patch("geoanalysis.analysis.roads.load_overture_roads", return_value=[invalid]):
            with self.assertRaises(RoadDataError):
                find_roads(COLLECTION)


class RoadSourceTests(unittest.TestCase):
    def test_worker_timeout_and_error_are_not_empty_results(self):
        with patch.object(source.subprocess, "run", side_effect=subprocess.TimeoutExpired("reader", 180)):
            with self.assertRaisesRegex(RoadDataError, "timed out"):
                source.load_overture_roads((-89, 43, -88.98, 43.02))

        def worker(command, **kwargs):
            Path(command[-1]).write_text(json.dumps({"error": "Coverage unavailable"}), encoding="utf-8")
            return SimpleNamespace(returncode=0)
        with patch.object(source.subprocess, "run", side_effect=worker):
            with self.assertRaisesRegex(RoadDataError, "Coverage unavailable"):
                source.load_overture_roads((-89, 43, -88.98, 43.02))

    def test_official_client_bbox_release_and_road_subtype(self):
        from shapely.geometry import LineString
        rows = [{"id": "road", "geometry": LineString(road()["geometry"]["coordinates"]).wkb, "subtype": "road"},
                {"id": "rail", "geometry": b"unused", "subtype": "rail"}]
        batch = MagicMock()
        batch.num_rows = 2
        batch.schema.names = ["id", "geometry", "subtype"]
        batch.select.return_value.to_pylist.return_value = deepcopy(rows)
        reader = MagicMock()
        reader.__iter__.return_value = iter([batch])
        bounds = (-89, 43, -88.98, 43.02)
        with patch("overturemaps.record_batch_reader", return_value=reader) as read:
            result = source._read_overture(bounds)
        self.assertEqual([feature["id"] for feature in result], ["overture:road"])
        read.assert_called_once_with("segment", bbox=bounds, release=source.RELEASE, stac=True,
                                     connect_timeout=10, request_timeout=30)
        reader.close.assert_called_once()
        reader.reset_mock()
        reader.__iter__.return_value = iter([batch])
        with patch("overturemaps.record_batch_reader", return_value=reader), patch.object(source, "MAX_SCANNED", 1):
            with self.assertRaisesRegex(RoadDataError, "Too many"):
                source._read_overture(bounds)
        reader.close.assert_called_once()

    def test_overpass_query_preserves_tags_and_rejects_partial_responses(self):
        payload = {"elements": [{"type": "way", "id": 42,
                   "tags": {"highway": "track", "access": "private", "bicycle": "yes"},
                   "geometry": [{"lon": -89, "lat": 43}, {"lon": -88.99, "lat": 43.01}]}]}
        response = MagicMock()
        response.__enter__.return_value = response
        response.iter_content.side_effect = lambda size: iter([json.dumps(payload).encode()])
        with patch.object(source.requests, "post", return_value=response) as post:
            result = source.load_osm_roads((-89, 43, -88.98, 43.02))
            self.assertEqual(result[0]["properties"]["tags"]["access"], "private")
            self.assertIn('(43,-89,43.02,-88.98)', post.call_args.kwargs["data"]["data"])
            payload["remark"] = "runtime error: Query timed out"
            with self.assertRaisesRegex(RoadDataError, "incomplete"):
                source.load_osm_roads((-89, 43, -88.98, 43.02))


class RoadUITests(unittest.TestCase):
    def result(self):
        with patch("geoanalysis.analysis.roads.load_overture_roads", return_value=[road()]):
            return find_roads(COLLECTION)

    def test_load_keeps_viewport_and_buildings_then_aoi_change_clears_roads(self):
        event = {"all_drawings": [AOI], "center": {"lat": 43.01, "lng": -88.99}, "zoom": 16}
        with patch("streamlit_folium.st_folium", return_value=event) as component, \
             patch("geoanalysis.ui.roads.find_roads", return_value=self.result()) as load:
            app = AppTest.from_file(APP).run()
            app.session_state.building_review = [{"type": "Feature", "id": "manual-test",
                "geometry": AOI["geometry"], "properties": {"origin": "manual", "status": "planned"}}]
            before_key = component.call_args.kwargs["key"]
            next(b for b in app.button if b.label == "Load roads").click().run()
            self.assertFalse(app.exception)
            load.assert_called_once()
            self.assertEqual(app.session_state.map_center, [43.01, -88.99])
            self.assertEqual(app.session_state.map_zoom, 16)
            self.assertEqual(component.call_args.kwargs["key"], before_key)
            self.assertEqual(len(app.session_state.building_review), 1)
            self.assertEqual(len(app.session_state.drawings), 1)
            self.assertEqual(len(component.call_args.kwargs["feature_group_to_add"]), 2)
            self.assertTrue(any(metric.label == "Mapped road/path length (Overture)" for metric in app.metric))
            app.checkbox(key="show_overture_roads").uncheck().run()
            self.assertEqual(len(component.call_args.kwargs["feature_group_to_add"]), 1)
            self.assertIn("road_result", app.session_state)
            component.return_value = {"all_drawings": []}
            app.run()
            self.assertNotIn("road_result", app.session_state)

    def test_failure_has_error_without_false_zero_and_keeps_last_success(self):
        with patch("streamlit_folium.st_folium", return_value={"all_drawings": [AOI]}), \
             patch("geoanalysis.ui.roads.find_roads", side_effect=RoadDataError("Road service unavailable")):
            app = AppTest.from_file(APP).run()
            next(b for b in app.button if b.label == "Load roads").click().run()
            self.assertFalse(app.exception)
            self.assertFalse(app.metric)
            self.assertTrue(any("Road service unavailable" in error.value for error in app.error))
            result = self.result()
            result["aoi_key"] = json.dumps([AOI["geometry"]], sort_keys=True)
            app.session_state.road_result = result
            next(b for b in app.button if b.label == "Load roads").click().run()
            self.assertIn("road_result", app.session_state)
            self.assertTrue(any("reload failed" in caption.value for caption in app.caption))

    def test_road_overlay_keeps_component_identity_and_escapes_names(self):
        result = self.result()
        result["overture"]["features"][0]["properties"]["name"] = '<img src=x onerror="alert(1)">'
        calls = []
        with patch.object(streamlit_folium, "_component_func", side_effect=lambda **kwargs: calls.append(kwargs)):
            streamlit_folium.st_folium(build_map([AOI], [43.01, -88.99], 16), key="test-map")
            streamlit_folium.st_folium(build_map([AOI], [43.01, -88.99], 16), key="test-map",
                                     feature_group_to_add=road_overlays(result))
        self.assertEqual(calls[0]["key"], calls[1]["key"])
        self.assertEqual(calls[0]["script"], calls[1]["script"])
        self.assertIn(r"\u0026lt;img", calls[1]["feature_group"])
        self.assertEqual(result["overture"]["features"][0]["properties"]["name"], '<img src=x onerror="alert(1)">')


if __name__ == "__main__":
    unittest.main()
