import csv
import io
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import brief_to_jira as b2j  # noqa: E402


def rows_of(csv_text):
    return list(csv.DictReader(io.StringIO(csv_text)))


class PriorityTests(unittest.TestCase):
    def test_aliases(self):
        cases = {
            "High": "High", "p0": "Highest", "P2": "Medium", "critical": "Highest",
            "Must have": "High", "nice to have": "Low", "**Low**": "Low",
            "High (launch blocker)": "High", "": "Medium",
        }
        for raw, expected in cases.items():
            self.assertEqual(b2j.normalize_priority(raw), expected, raw)

    def test_unknown_raises(self):
        with self.assertRaises(ValueError):
            b2j.normalize_priority("whenever")


class ParseTests(unittest.TestCase):
    def test_example_brief(self):
        text = (ROOT / "examples" / "checkout_brief.md").read_text()
        brief = b2j.parse_brief(text)
        self.assertEqual(brief.feature_title, "Checkout Redesign")
        self.assertEqual(
            [s.title for s in brief.stories],
            ["Guest checkout", "Saved payment methods", "Address autocomplete"],
        )
        guest = brief.stories[0]
        self.assertEqual(guest.labels, ["checkout", "mvp"])
        self.assertEqual(guest.story_points, "5")
        self.assertEqual(guest.components, ["Web"])
        self.assertEqual(len(guest.acceptance_criteria), 3)
        # Continuation line folded into the criterion.
        self.assertIn("then a confirmation email", guest.acceptance_criteria[1])
        self.assertNotIn("Priority", guest.description)

    def test_unprefixed_headings_are_stories(self):
        text = "# Feat\n\n## One\nDesc one\n\n## Two\nDesc two\n"
        brief = b2j.parse_brief(text)
        self.assertEqual([s.title for s in brief.stories], ["One", "Two"])

    def test_explicit_story_level(self):
        text = "## Epic A\n### Login\nx\n### Logout\ny\n"
        brief = b2j.parse_brief(text, story_level=3)
        self.assertEqual([s.title for s in brief.stories], ["Login", "Logout"])

    def test_story_ends_at_next_section(self):
        text = "## Story: A\nbody\n### Acceptance Criteria\n- one\n## Appendix\njunk\n"
        brief = b2j.parse_brief(text)
        self.assertEqual(len(brief.stories), 1)
        self.assertEqual(brief.stories[0].acceptance_criteria, ["one"])
        self.assertNotIn("junk", brief.stories[0].description)

    def test_nested_ac_items_fold_into_parent(self):
        text = "## Story: A\n### Acceptance Criteria\n- parent\n  - child\n- next\n"
        ac = b2j.parse_brief(text).stories[0].acceptance_criteria
        self.assertEqual(ac, ["parent child", "next"])

    def test_headings_in_code_fence_ignored(self):
        text = "## Story: A\n```\n## not a story\n```\n"
        brief = b2j.parse_brief(text)
        self.assertEqual(len(brief.stories), 1)
        self.assertIn("## not a story", brief.stories[0].description)


class CsvTests(unittest.TestCase):
    def test_columns_and_values(self):
        text = (ROOT / "examples" / "checkout_brief.md").read_text()
        csv_text, warnings = b2j.convert(text, parent="SHOP-1")
        self.assertEqual(warnings, [])
        header = next(csv.reader(io.StringIO(csv_text)))
        self.assertEqual(header[:5], ["Summary", "Issue Type", "Priority", "Description",
                                      "Acceptance Criteria"])
        self.assertEqual(header.count("Labels"), 2)
        self.assertIn("Parent", header)
        rows = rows_of(csv_text)
        self.assertEqual([r["Priority"] for r in rows], ["High", "Medium", "Low"])
        self.assertTrue(rows[0]["Acceptance Criteria"].startswith("* Given I am not signed in"))
        self.assertIn("*first-time shopper*", rows[0]["Description"])

    def test_ac_in_description_plain(self):
        text = "## Story: A\nAs a user...\n\nAcceptance Criteria:\n- works\n"
        csv_text, _ = b2j.convert(text, markup="plain", ac_in_description=True)
        row = rows_of(csv_text)[0]
        self.assertIn("Acceptance Criteria:\n- works", row["Description"])
        self.assertEqual(row["Acceptance Criteria"], "- works")

    def test_bad_priority_warns_or_fails(self):
        text = "## Story: A\nPriority: someday\n- x\n"
        _, warnings = b2j.convert(text)
        self.assertTrue(any("Unrecognised priority" in w for w in warnings))
        with self.assertRaises(ValueError):
            b2j.convert(text, strict=True)

    def test_labels_have_no_spaces_and_feature_label(self):
        text = "# Feature: Big Thing\n## Story: A\nLabels: front end\n"
        csv_text, _ = b2j.convert(text, feature_label=True, extra_labels=["q1"])
        reader = csv.reader(io.StringIO(csv_text))
        header, row = next(reader), next(reader)
        labels = [v for h, v in zip(header, row) if h == "Labels"]
        self.assertEqual(labels, ["front-end", "q1", "Big-Thing"])

    def test_cli_writes_file(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "out.csv"
            rc = b2j.main([str(ROOT / "examples" / "checkout_brief.md"), "-o", str(out)])
            self.assertEqual(rc, 0)
            self.assertEqual(len(rows_of(out.read_text())), 3)


if __name__ == "__main__":
    unittest.main()
