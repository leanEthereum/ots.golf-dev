"""Chart rendering remains bounded, accessible and safe for submitted attribution."""
from __future__ import annotations

from datetime import datetime, timedelta
import json
import unittest
import xml.etree.ElementTree as ET

from app.charts import _nice_ticks, record_chart
from app.literature import EQUAL_CHAINS


class ChartTests(unittest.TestCase):
    def test_axis_size_is_bounded_through_maximum_admissible_claim(self):
        for high in (1, 18, 93, 106, 250, 1000, 1_000_000):
            with self.subTest(high=high):
                ticks = _nice_ticks(0, high)
                self.assertLessEqual(len(ticks), 9)
                self.assertEqual(ticks, sorted(set(ticks)))
                self.assertTrue(all(0 <= tick <= high for tick in ticks))
        chart = record_chart([self.series(1_000_000)], datetime(2026, 1, 1))
        self.assertLess(len(chart['svg']), 6000)

    @staticmethod
    def series(claim=93, points=None):
        points = points or [{'t': datetime(2025, 12, 30), 'claim': claim, 'login': 'solver', 'id': 'id'}]
        return {'slug': 'lower-generality-1', 'framework': 'generality-1', 'kind': 'lower',
                'label': 'Generality 1/3 lower', 'status': 'certified', 'points': points}

    def test_attribution_cannot_escape_svg_or_json_script(self):
        stamp = datetime(2026, 1, 1)
        login = '</script><script>alert("x")</script>'
        point = {'t': stamp, 'claim': 93, 'login': login, 'id': 'a" onload="bad', 'demo': True}
        chart = record_chart([self.series(points=[point])], stamp + timedelta(days=1))
        svg = ET.fromstring(chart['svg'])
        self.assertEqual(svg.get('role'), 'group')
        self.assertEqual(svg.findall('.//script'), [])
        self.assertNotIn('<', chart['points'])
        self.assertEqual(json.loads(chart['points'])[0]['login'], login)
        link = svg.find('.//a')
        self.assertIn(login, link.get('aria-label'))
        self.assertNotIn('onload', link.attrib)

    def test_demo_marks_and_endpoints_are_labeled_without_marking_real_results(self):
        stamp = datetime(2026, 1, 1)
        for demo in (True, False):
            with self.subTest(demo=demo):
                point = {'t': stamp, 'claim': 93, 'login': 'solver', 'id': 'id', 'demo': demo}
                chart = record_chart([self.series(points=[point])], stamp + timedelta(days=1))
                svg = ET.fromstring(chart['svg'])
                link = svg.find('.//a')
                self.assertEqual(' · demo' in link.get('aria-label'), demo)
                self.assertEqual(' · demo' in link.find('.//title').text, demo)
                self.assertEqual(' · demo' in ''.join(svg.find("./g/text[@class='label']").itertext()), demo)
                self.assertEqual(json.loads(chart['points'])[0]['demo'], demo)

    def test_equal_endpoint_labels_remain_separate(self):
        series = [dict(self.series(93), slug=slug) for slug in ('first', 'second', 'third')]
        svg = ET.fromstring(record_chart(series, datetime(2026, 1, 1))['svg'])
        ys = [float(t.get('y')) for t in svg.findall("./g/text[@class='label']")]
        self.assertEqual(len(set(ys)), 3)
        self.assertGreaterEqual(min(abs(a - b) for i, a in enumerate(ys) for b in ys[i + 1:]), 28)

    def test_series_without_records_draws_nothing(self):
        empty = dict(self.series(), points=[])
        svg = ET.fromstring(record_chart([empty], datetime(2026, 1, 1))['svg'])
        self.assertEqual(svg.findall('./g'), [])
        self.assertIn('No records yet', [t.text for t in svg.findall('./text')])
        svg = ET.fromstring(record_chart([empty, self.series()], datetime(2026, 1, 1))['svg'])
        self.assertEqual(len(svg.findall('./g')), 1)
        self.assertNotIn('No records yet', [t.text for t in svg.findall('./text')])

    def test_future_timestamp_is_inside_chart_axis(self):
        now = datetime(2026, 1, 1)
        point = {'t': now + timedelta(minutes=2), 'claim': 93, 'login': 'solver', 'id': 'id'}
        chart = record_chart([self.series(points=[point])], now)
        svg = ET.fromstring(chart['svg'])
        axis_right = float(svg.find("./line[@class='axis']").get('x2'))
        self.assertLessEqual(json.loads(chart['points'])[0]['x'], axis_right)

    def test_reference_has_no_record_and_shares_label_collision_layout(self):
        chart = record_chart([self.series(105)], datetime(2026, 1, 1), references=(EQUAL_CHAINS,))
        svg = ET.fromstring(chart['svg'])
        self.assertEqual(len(json.loads(chart['points'])), 1)
        self.assertEqual(len(svg.findall(".//a[@class='chart-record']")), 1)
        reference = svg.find("./g[@class='chart-reference']")
        self.assertEqual(reference.find('./a').get('href'), EQUAL_CHAINS['url'])
        ys = [float(t.get('y')) for t in svg.findall(".//text[@class='label']")]
        self.assertGreaterEqual(abs(ys[0] - ys[1]), 28)

    def test_reference_sets_axis_even_without_records(self):
        svg = ET.fromstring(record_chart([], datetime(2026, 1, 1), references=(EQUAL_CHAINS,))['svg'])
        self.assertIn('No records yet', [t.text for t in svg.findall('./text')])
        ticks = [int(t.text) for t in svg.findall("./text[@text-anchor='end']")]
        self.assertLess(min(ticks), 105)
        self.assertGreater(max(ticks), 105)


if __name__ == '__main__':
    unittest.main()
