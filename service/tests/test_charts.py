"""Chart rendering remains bounded, accessible and safe for submitted attribution."""
from __future__ import annotations

from datetime import datetime, timedelta
import json
import unittest
import xml.etree.ElementTree as ET

from app.charts import _log_axis, record_chart
from app.literature import EQUAL_CHAINS


class ChartTests(unittest.TestCase):
    def test_axis_size_is_bounded_through_maximum_admissible_claim(self):
        for high in (1, 18, 93, 106, 250, 1000, 1_000_000):
            with self.subTest(high=high):
                floor, ceiling, ticks = _log_axis(1, high)
                self.assertLessEqual(len(ticks), 9)
                self.assertEqual(ticks, sorted(set(ticks)))
                self.assertEqual(floor, 1)
                self.assertLessEqual(ticks[-1], ceiling)
                self.assertGreater(ceiling, high)
                self.assertTrue(all(1 <= tick <= ceiling for tick in ticks))
        chart = record_chart([self.series(1_000_000)], datetime(2026, 1, 1))
        self.assertLess(len(chart['svg']), 6000)

    def test_axis_fits_narrow_ranges_and_single_records(self):
        for low, high in ((393, 426), (90, 1140), (702, 702), (1_000_000, 1_000_000)):
            with self.subTest(low=low, high=high):
                floor, ceiling, ticks = _log_axis(low, high)
                self.assertGreater(floor, low / 2)
                self.assertLess(floor, low)
                self.assertGreater(ceiling, high)
                self.assertLess(ceiling, high * 2)
                self.assertTrue(2 <= len(ticks) <= 9)
                self.assertTrue(all(floor <= t <= ceiling for t in ticks))

    def test_close_records_use_the_plot_height(self):
        stamp = datetime(2026, 1, 1)
        points = [dict(t=stamp + timedelta(hours=i), claim=value, login='solver', id=str(i))
                  for i, value in enumerate((426, 393))]
        chart = record_chart([self.series(points=points)], stamp + timedelta(days=1))
        rendered = json.loads(chart['points'])
        self.assertGreater(rendered[1]['y'] - rendered[0]['y'], 250)

    def test_equal_ratios_have_equal_spacing_and_one_is_at_baseline(self):
        stamp = datetime(2026, 1, 1)
        points = [dict(t=stamp + timedelta(hours=i), claim=value, login='solver', id=str(i))
                  for i, value in enumerate((1, 10, 100, 1000))]
        chart = record_chart([self.series(points=points)], stamp + timedelta(days=1))
        svg = ET.fromstring(chart['svg'])
        rendered = json.loads(chart['points'])
        self.assertEqual(svg.get('data-y-scale'), 'log')
        self.assertEqual(rendered[0]['y'], float(svg.find("./line[@class='axis']").get('y1')))
        gaps = [a['y'] - b['y'] for a, b in zip(rendered, rendered[1:])]
        self.assertLess(max(gaps) - min(gaps), 0.2)
        self.assertEqual([p['claim'] for p in rendered], [1, 10, 100, 1000])

    def test_zero_is_not_misrepresented_as_one(self):
        chart = record_chart([self.series(0)], datetime(2026, 1, 1))
        self.assertEqual(json.loads(chart['points']), [])
        self.assertIn('zero-valued record', chart['svg'])
        svg = ET.fromstring(chart['svg'])
        self.assertEqual(svg.findall(".//circle[@class='mark']"), [])

    def test_records_and_reference_use_identical_log_coordinates(self):
        chart = record_chart([self.series(105)], datetime(2026, 1, 1), references=(EQUAL_CHAINS,))
        svg = ET.fromstring(chart['svg'])
        y = json.loads(chart['points'])[0]['y']
        ref = svg.find("./g[@class='chart-reference']/path[@class='line']")
        self.assertIn(f',{y:.1f} H', ref.get('d'))

    @staticmethod
    def series(claim=93, points=None):
        points = points or [{'t': datetime(2025, 12, 30), 'claim': claim, 'login': 'solver', 'id': 'id'}]
        return {'slug': 'lower-generality-1', 'framework': 'generality-1', 'kind': 'lower',
                'label': 'Lower bound · whole words', 'status': 'certified', 'points': points}

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

    def test_demo_marks_keep_attribution_without_suffixing_endpoint_labels(self):
        stamp = datetime(2026, 1, 1)
        for demo in (True, False):
            with self.subTest(demo=demo):
                point = {'t': stamp, 'claim': 93, 'login': 'solver', 'id': 'id', 'demo': demo}
                chart = record_chart([self.series(points=[point])], stamp + timedelta(days=1))
                svg = ET.fromstring(chart['svg'])
                link = svg.find('.//a')
                self.assertEqual(' · demo' in link.get('aria-label'), demo)
                self.assertEqual(' · demo' in link.find('.//title').text, demo)
                self.assertNotIn(' · demo', ''.join(svg.find("./g/text[@class='label']").itertext()))
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
