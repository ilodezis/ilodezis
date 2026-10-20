import unittest

from stats import current_streak, language_shares, render_langs, render_overview


def repo(langs, archived=False):
    return {"isArchived": archived, "languages": {"edges": [
        {"size": size, "node": {"name": name, "color": "#000000"}} for name, size in langs
    ]}}


class StreakTest(unittest.TestCase):
    def test_counts_back_from_today(self):
        days = [("d1", 0), ("d2", 3), ("d3", 1), ("d4", 2)]
        self.assertEqual(current_streak(days), 3)

    def test_empty_today_does_not_break_streak(self):
        days = [("d1", 1), ("d2", 1), ("d3", 0)]
        self.assertEqual(current_streak(days), 2)

    def test_gap_yesterday_resets(self):
        days = [("d1", 5), ("d2", 0), ("d3", 0)]
        self.assertEqual(current_streak(days), 0)

    def test_empty(self):
        self.assertEqual(current_streak([]), 0)


class LanguagesTest(unittest.TestCase):
    def test_skips_archived_and_merges_css(self):
        shares, count = language_shares([
            repo([("Python", 60), ("CSS", 20)]),
            repo([("HTML", 20)]),
            repo([("HTML", 10_000)], archived=True),
        ])
        self.assertEqual(count, 2)
        self.assertEqual([(l, round(p)) for l, _, p in shares],
                         [("Python", 60), ("HTML / CSS", 40)])

    def test_tail_folds_into_other(self):
        shares, _ = language_shares([repo([(f"L{i}", 10 - i) for i in range(8)])])
        self.assertEqual(len(shares), 6)
        self.assertEqual(shares[-1][0], "Other")
        self.assertAlmostEqual(sum(p for _, _, p in shares), 100)

    def test_no_languages(self):
        self.assertEqual(language_shares([repo([])]), ([], 0))


class RenderTest(unittest.TestCase):
    def test_overview_contains_values(self):
        svg = render_overview({"total": 1227, "past_year": 1212, "repos": [{}] * 46, "streak": 1}, "dark")
        for text in ("1,227", "1,212", ">46<", "1 day<"):
            self.assertIn(text, svg)

    def test_bar_ends_flush(self):
        shares = [("A", "#111111", 55.5), ("B", "#222222", 30.25), ("Other", None, 14.25)]
        svg = render_langs(shares, 3, "light")
        last = svg.split('<rect x="')[-1]
        x, width = int(last.split('"')[0]), int(last.split('width="')[1].split('"')[0])
        self.assertEqual(x + width, 390)
        self.assertIn("across 3 repos", svg)


if __name__ == "__main__":
    unittest.main()
