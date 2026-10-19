"""Manual review, planning, and refresh regression tests."""

from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from shapely.geometry import MultiPolygon, box, mapping
from streamlit.testing.v1 import AppTest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from geoanalysis.core.building_review import (
    editing_parts, merge_analysis, review_counts, source_buildings, validate_building_edits,
)

APP = str(Path(__file__).resolve().parents[1] / "src/geoanalysis/ui/app.py")


def feature(identity, geometry, status="existing", origin="manual"):
    return {"type": "Feature", "id": identity, "geometry": json.loads(json.dumps(mapping(geometry))),
            "properties": {"origin": origin, "status": status, "role": "building"}}


AOI = [feature("aoi", box(0, 0, 0.1, 0.1))]
SOURCES = [feature("source-a", box(0.01, 0.01, 0.02, 0.02)),
           feature("source-b", box(0.03, 0.03, 0.04, 0.04))]


class ReviewTests(unittest.TestCase):
    def test_add_delete_plan_and_refresh_preserve_corrections(self):
        sources = source_buildings(SOURCES)
        manual = feature("manual-added", box(0.05, 0.05, 0.06, 0.06))
        planned = feature("manual-planned", box(0.07, 0.07, 0.08, 0.08), status="planned")
        reviewed = validate_building_edits(editing_parts([sources[1], manual, planned]), AOI, SOURCES)
        self.assertEqual(review_counts(reviewed), {"existing": 2, "planned": 1})
        refreshed = merge_analysis(SOURCES, reviewed, ["source-a"])
        self.assertEqual({f["id"] for f in refreshed}, {"source-b", "manual-added", "manual-planned"})
        self.assertEqual(review_counts(refreshed), {"existing": 2, "planned": 1})

    def test_adjusted_source_geometry_survives_refresh(self):
        working = source_buildings(SOURCES)
        working[0]["geometry"] = feature("unused", box(0.011, 0.011, 0.021, 0.021))["geometry"]
        reviewed = validate_building_edits(editing_parts(working), AOI, SOURCES)
        adjusted = next(f for f in reviewed if f["id"] == "source-a")
        self.assertTrue(adjusted["properties"]["manually_edited"])
        refreshed = merge_analysis(SOURCES, reviewed, [])
        self.assertEqual(next(f for f in refreshed if f["id"] == "source-a")["geometry"], adjusted["geometry"])

    def test_multipart_counts_as_one_and_retains_parent_identity(self):
        source = [feature("multipart", MultiPolygon([box(0.01, 0.01, 0.02, 0.02), box(0.03, 0.03, 0.04, 0.04)]))]
        parts = editing_parts(source_buildings(source))
        self.assertEqual(len(parts), 2)
        reviewed = validate_building_edits(parts, AOI, source)
        self.assertEqual(len(reviewed), 1)
        self.assertEqual(reviewed[0]["id"], "multipart")
        self.assertEqual(reviewed[0]["geometry"]["type"], "MultiPolygon")
        self.assertEqual(len(validate_building_edits(parts[:1], AOI, source)), 1)

    def test_rejects_outside_duplicate_and_invalid_shapes_without_mutating(self):
        valid = feature("manual", box(0.01, 0.01, 0.02, 0.02))
        outside = feature("outside", box(1, 1, 2, 2))
        duplicate = deepcopy(valid)
        duplicate["id"] = "duplicate"
        invalid = deepcopy(valid)
        invalid["geometry"]["coordinates"] = [[[0, 0], [0.1, 0.1], [0, 0.1], [0.1, 0], [0, 0]]]
        original = deepcopy(valid)
        for parts in ([valid, outside], [valid, duplicate], [valid, invalid]):
            with self.subTest(parts=parts), self.assertRaises(ValueError):
                validate_building_edits(parts, AOI, [])
        self.assertEqual(valid, original)


class ReviewUITests(unittest.TestCase):
    def test_building_changes_keep_aoi_and_undo_restores_review(self):
        with patch("streamlit_folium.st_folium", return_value={"all_drawings": AOI}) as component:
            app = AppTest.from_file(APP).run()
            app.session_state.building_result = {
                "geojson": {"type": "FeatureCollection", "features": SOURCES}, "count": 2,
                "release": "2026-08-13", "skipped": 0,
                "aoi_key": json.dumps([f["geometry"] for f in AOI], sort_keys=True),
            }
            app.session_state.building_review = source_buildings(SOURCES)
            component.return_value = {"all_drawings": None}
            app.run()
            app.radio[0].set_value("Buildings").run()
            self.assertFalse(app.exception)
            component.return_value = {"all_drawings": editing_parts(source_buildings(SOURCES)[1:])}
            app.run()
            self.assertFalse(app.exception)
            self.assertEqual(app.session_state.drawings, AOI)
            self.assertIn("building_result", app.session_state)
            self.assertEqual(app.metric[0].value, "1")
            self.assertEqual(app.session_state.removed_buildings, ["source-a"])
            component.return_value = {"all_drawings": None}
            next(b for b in app.button if b.label == "Undo last building edit").click().run()
            self.assertFalse(app.exception)
            self.assertEqual(app.metric[0].value, "2")
            self.assertEqual(app.session_state.removed_buildings, [])

    def test_planning_without_analysis_and_invalid_draft(self):
        with patch("streamlit_folium.st_folium", return_value={"all_drawings": AOI}) as component:
            app = AppTest.from_file(APP).run()
            component.return_value = {"all_drawings": None}
            app.run()
            app.radio[0].set_value("Buildings").run()
            app.radio[1].set_value("Planned building").run()
            planned = feature("manual-plan", box(0.01, 0.01, 0.02, 0.02), status="planned")
            component.return_value = {"all_drawings": editing_parts([planned])}
            app.run()
            self.assertFalse(app.exception)
            self.assertEqual([m.value for m in app.metric], ["0", "1"])
            self.assertNotIn("building_result", app.session_state)
            component.return_value = {"all_drawings": editing_parts([planned, feature("outside", box(1, 1, 2, 2))])}
            app.run()
            self.assertFalse(app.exception)
            self.assertTrue(app.error)
            self.assertEqual([m.value for m in app.metric], ["0", "1"])
            self.assertEqual(len(app.session_state.building_review), 1)
            self.assertTrue(app.session_state.building_draft)


if __name__ == "__main__":
    unittest.main()
