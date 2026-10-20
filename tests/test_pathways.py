"""Pathway geometry, geodesic measurements, and isolated editing regressions."""

from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from shapely.geometry import box, mapping
from streamlit.testing.v1 import AppTest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from geoanalysis.core.pathways import pathway_collection, validate_pathways
from geoanalysis.ui.app import build_map
from geoanalysis.ui.pathways import pathway_overlays

APP = str(Path(__file__).resolve().parents[1] / "src/geoanalysis/ui/app.py")
AOI = [{"type": "Feature", "geometry": json.loads(json.dumps(mapping(box(0, 0, 0.1, 0.1)))), "properties": {}}]


def path(identity="path-1", coordinates=None, status="planned"):
    return {"type": "Feature", "id": identity,
            "geometry": {"type": "LineString", "coordinates": coordinates or [[0.01, 0.01], [0.02, 0.01]]},
            "properties": {"role": "pathway", "review_id": identity, "status": status}}


class PathwayTests(unittest.TestCase):
    def test_valid_extension_ids_status_provenance_and_geodesic_length(self):
        original = path(coordinates=[[0, 0.01], [0.01, 0.01]])
        before = deepcopy(original)
        reviewed = validate_pathways([original], AOI)
        self.assertEqual(original, before)
        self.assertAlmostEqual(reviewed[0]["properties"]["length_m"], 1113.19, delta=0.1)
        self.assertEqual(reviewed[0]["properties"]["public_access"], "unverified")
        original["geometry"]["coordinates"].append([0.02, 0.01])
        original["properties"]["status"] = "existing"
        original["properties"]["public_access"] = "yes"
        extended = validate_pathways([original], AOI)
        self.assertEqual(extended[0]["id"], reviewed[0]["id"])
        self.assertGreater(extended[0]["properties"]["length_m"], reviewed[0]["properties"]["length_m"])
        self.assertEqual(extended[0]["properties"]["status"], "existing")
        self.assertEqual(extended[0]["properties"]["public_access"], "unverified")
        self.assertEqual(pathway_collection(extended)["features"], extended)
        self.assertEqual(validate_pathways([], AOI), [])

    def test_outside_holes_boundary_only_invalid_duplicates_and_limits_rejected(self):
        holed = deepcopy(AOI)
        holed[0]["geometry"] = json.loads(json.dumps(mapping(box(0, 0, 0.1, 0.1).difference(box(0.03, 0.03, 0.07, 0.07)))))
        invalid = [path(coordinates=[[0, 0], [0.1, 0]]), path(coordinates=[[0.01, 0.01], [0.2, 0.02]]),
                   path(coordinates=[[0.02, 0.05], [0.08, 0.05]]),
                   path(coordinates=[[0.01, 0.01], [0.01, 0.01]]),
                   path(coordinates=[[0.01, 0.01], [float("nan"), 0.02]]),
                   path(coordinates=[[0.01, 0.01], [True, 0.02]]),
                   path(coordinates=[[0.01, 0.01, 3], [0.02, 0.02, 4]]),
                   path(coordinates=[[0.01, 0.01], [0.02, 0.02], [0.01, 0.02], [0.02, 0.01]]),
                   path(status="public")]
        for feature in invalid:
            with self.subTest(feature=feature), self.assertRaises(ValueError):
                validate_pathways([feature], holed)
        with self.assertRaises(ValueError):
            validate_pathways([path(), path("reversed", list(reversed(path()["geometry"]["coordinates"])))], AOI)
        with self.assertRaises(ValueError):
            validate_pathways([path(), path(coordinates=[[0.04, 0.01], [0.05, 0.01]])], AOI)
        with patch("geoanalysis.core.pathways.MAX_PATHWAYS", 0), self.assertRaises(ValueError):
            validate_pathways([path()], AOI)
        with self.assertRaises(ValueError):
            validate_pathways([path()], [])

    def test_editor_script_identity_and_line_tools(self):
        import streamlit_folium
        with patch("streamlit_folium._component_func", return_value={}) as component:
            streamlit_folium.st_folium(build_map(pathway_editor=True, new_status="planned"), key="path-test")
            streamlit_folium.st_folium(build_map([path()], [0.01, 0.01], 16,
                                               pathway_editor=True, new_status="planned"), key="path-test")
        first, second = [call.kwargs for call in component.call_args_list]
        self.assertEqual(first["script"], second["script"])
        self.assertIn('"polyline": {', second["script"])
        self.assertIn('"polygon": false', second["script"])
        self.assertIn("saved.pathway_editor ? 'pathway' : 'building'", second["script"])
        self.assertEqual(len(pathway_overlays(validate_pathways([path()], AOI))), 1)


class PathwayUITests(unittest.TestCase):
    def test_draw_extend_delete_undo_invalid_discard_mode_switch_and_clear(self):
        with patch("streamlit_folium.st_folium", return_value={"all_drawings": AOI}) as component:
            app = AppTest.from_file(APP).run()
            component.return_value = {"all_drawings": None}
            app.session_state.map_center = [0.02, 0.02]
            app.session_state.map_zoom = 16
            building = {**deepcopy(AOI[0]), "id": "manual-building",
                        "properties": {"origin": "manual", "status": "planned", "role": "building"}}
            app.session_state.building_review = [building]
            app.run()
            app.radio[0].set_value("Pathways").run()
            self.assertFalse(app.exception)
            component.return_value = {"all_drawings": [path()]}
            app.run()
            self.assertEqual(len(app.session_state.pathway_review), 1)
            self.assertEqual(app.session_state.drawings, AOI)
            self.assertEqual(app.session_state.building_review, [building])
            self.assertEqual(app.session_state.map_center, [0.02, 0.02])
            self.assertEqual(app.session_state.map_zoom, 16)
            extended = path(coordinates=[[0.01, 0.01], [0.02, 0.01], [0.025, 0.015]])
            component.return_value = {"all_drawings": [extended]}
            app.run()
            accepted = deepcopy(app.session_state.pathway_review)
            self.assertEqual(accepted[0]["geometry"], extended["geometry"])
            component.return_value = {"all_drawings": []}
            app.run()
            self.assertEqual(app.session_state.pathway_review, [])
            component.return_value = {"all_drawings": None}
            next(b for b in app.button if b.label == "Undo last pathway edit").click().run()
            self.assertEqual(app.session_state.pathway_review, accepted)
            component.return_value = {"all_drawings": [path(coordinates=[[1, 1], [2, 2]])]}
            app.run()
            self.assertEqual(app.session_state.pathway_review, accepted)
            self.assertTrue(app.session_state.pathway_edit_error)
            self.assertTrue(any(b.disabled for b in app.get("download_button") if b.label == "Download pathway sketches GeoJSON"))
            component.return_value = {"all_drawings": None}
            next(b for b in app.button if b.label == "Discard unsaved pathway edits").click().run()
            self.assertNotIn("pathway_draft", app.session_state)
            app.radio[0].set_value("Buildings").run()
            self.assertEqual(app.session_state.pathway_review, accepted)
            self.assertEqual(app.session_state.building_review, [building])
            app.radio[0].set_value("AOI boundaries").run()
            component.return_value = {"all_drawings": []}
            app.run()
            self.assertNotIn("pathway_review", app.session_state)
            self.assertNotIn("pathway_undo", app.session_state)
            self.assertFalse(app.exception)


if __name__ == "__main__":
    unittest.main()
