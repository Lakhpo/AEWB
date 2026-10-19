"""Regression checks for AOI confirmation and map recovery."""

import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest
import streamlit_folium

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from geoanalysis.ui.app import build_map, building_overlay

APP = str(Path(__file__).resolve().parents[1] / "src/geoanalysis/ui/app.py")
POLYGON = {"type": "Feature", "properties": {}, "geometry": {
    "type": "Polygon", "coordinates": [[[-89, 43], [-88, 43], [-88, 44], [-89, 43]]],
}}


class SelectionUITests(unittest.TestCase):
    def test_analysis_count_overlay_and_invalidation(self):
        small = {"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [
            [[-89, 43], [-88.99, 43], [-88.99, 43.01], [-89, 43]],
        ]}}
        event = {"all_drawings": [small], "center": {"lat": 43, "lng": -89}, "zoom": 16}
        result = {"count": 1, "geojson": {"type": "FeatureCollection", "features": [small]},
                  "release": "2026-08-13", "skipped": 0}
        with patch("streamlit_folium.st_folium", return_value=event) as component, \
             patch("geoanalysis.analysis.analysis.find_buildings", return_value=result) as analysis:
            app = AppTest.from_file(APP).run()
            run = next(button for button in app.button if button.label == "Run Analysis")
            run.click().run()
            self.assertFalse(app.exception)
            analysis.assert_called_once()
            self.assertEqual(app.metric[0].value, "1")
            self.assertIsNotNone(component.call_args.kwargs["feature_group_to_add"])
            # Panning keeps the result; changed boundary geometry removes it.
            app.run()
            self.assertTrue(app.metric)
            component.return_value = {"all_drawings": [POLYGON]}
            app.run()
            self.assertFalse(app.metric)
            self.assertNotIn("building_result", app.session_state)

    def test_analysis_error_does_not_show_zero_count(self):
        from geoanalysis.services.buildings import BuildingDataError
        event = {"all_drawings": [POLYGON]}
        with patch("streamlit_folium.st_folium", return_value=event), \
             patch("geoanalysis.analysis.analysis.find_buildings", side_effect=BuildingDataError("Source unavailable")):
            app = AppTest.from_file(APP).run()
            next(button for button in app.button if button.label == "Run Analysis").click().run()
        self.assertFalse(app.exception)
        self.assertFalse(app.metric)
        self.assertIn("Source unavailable", app.error[0].value)

    def test_selection_survives_reruns_with_visible_geojson(self):
        event = {"all_drawings": [POLYGON], "center": {"lat": 43.5, "lng": -88.5}, "zoom": 15}
        with patch("streamlit_folium.st_folium", return_value=event):
            app = AppTest.from_file(APP).run()
        self.assertFalse(app.exception)
        self.assertIn("selected successfully", app.success[0].value)
        self.assertEqual(json.loads(app.code[0].value)["features"][0]["geometry"], POLYGON["geometry"])
        # The component can return no selection/center before initialization.
        with patch("streamlit_folium.st_folium", return_value={"all_drawings": None, "zoom": 4}) as component:
            app.run()
        self.assertFalse(app.exception)
        self.assertEqual(app.session_state.drawings, [POLYGON])
        self.assertEqual(app.session_state.map_zoom, 15)
        self.assertEqual(component.call_args.kwargs["center"], [43.5, -88.5])
        self.assertEqual(component.call_args.kwargs["zoom"], 15)
        self.assertTrue(app.success)

    def test_delete_and_clear_remove_success_and_keep_location(self):
        event = {"all_drawings": [POLYGON], "center": {"lat": 43, "lng": -89}, "zoom": 16}
        with patch("streamlit_folium.st_folium", return_value=event):
            app = AppTest.from_file(APP).run()
        with patch("streamlit_folium.st_folium", return_value={"all_drawings": None}):
            app.sidebar.button[0].click().run()
        self.assertFalse(app.exception)
        self.assertFalse(app.success)
        self.assertEqual(app.session_state.drawings, [])
        self.assertEqual(app.session_state.map_center, [43, -89])
        with patch("streamlit_folium.st_folium", return_value=event):
            app.run()
        with patch("streamlit_folium.st_folium", return_value={"all_drawings": []}):
            app.run()
        self.assertEqual(app.session_state.drawings, [])
        self.assertFalse(app.success)

    def test_recovery_data_does_not_change_component_identity(self):
        calls = []
        with patch.object(streamlit_folium, "_component_func", side_effect=lambda **kw: calls.append(kw)):
            streamlit_folium.st_folium(build_map(), key="map")
            streamlit_folium.st_folium(build_map([POLYGON], [43, -89], 16), key="map")
        self.assertEqual(calls[0]["key"], calls[1]["key"])
        self.assertEqual(calls[0]["script"], calls[1]["script"])
        self.assertNotEqual(calls[0]["html"], calls[1]["html"])
        self.assertIn('"zoom": 16', calls[1]["html"])
        self.assertIn("drawnItems.addLayer(layer)", calls[1]["script"])

    def test_result_overlay_does_not_remount_map(self):
        calls = []
        result = {"count": 1, "geojson": {"type": "FeatureCollection", "features": [POLYGON]}}
        with patch.object(streamlit_folium, "_component_func", side_effect=lambda **kw: calls.append(kw)):
            streamlit_folium.st_folium(build_map([POLYGON], [43, -89], 16), key="map")
            streamlit_folium.st_folium(build_map([POLYGON], [43, -89], 16), key="map",
                                     feature_group_to_add=building_overlay(result))
        self.assertEqual(calls[0]["key"], calls[1]["key"])
        self.assertEqual(calls[0]["script"], calls[1]["script"])
        self.assertIn("Building footprint", calls[1]["feature_group"])
        self.assertIsNone(building_overlay({"count": 0}))


if __name__ == "__main__":
    unittest.main()
