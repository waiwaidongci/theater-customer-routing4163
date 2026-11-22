"""规则版本化验收的纯领域测试：不依赖数据库，可用 `python -m unittest` 直接运行。"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.domain.analysis import analyze
from src.domain.demo import DEMO_RULES, demo_rows
from src.domain.rules import display, find_overlap, moment, resolve
from src.services.validation import cell, display_moment


def snapshot(*indexes):
    return [dict(DEMO_RULES[index]) for index in indexes]


class MomentTest(unittest.TestCase):
    def test_parse_and_display(self):
        self.assertEqual(moment('2026-11-20T09:00:00+08:00').isoformat(), '2026-11-20T01:00:00')
        self.assertEqual(moment('2026-11-20 09:00 +08:00'.replace(' ', 'T', 1)).isoformat(), '2026-11-20T01:00:00')
        self.assertEqual(display('2026-11-20T01:00:00+00:00'), '2026-11-20T09:00:00+08:00')

    def test_cell_defaults_to_beijing(self):
        field = {'label': '到件时间', 'type': 'datetime'}
        self.assertEqual(cell(field, '2026-11-20 09:00:00'), '2026-11-20T01:00:00+00:00')
        self.assertEqual(cell(field, '2026-11-20T01:00:00Z'), '2026-11-20T01:00:00+00:00')
        self.assertEqual(display_moment('2026-11-20T01:00:00+00:00'), '2026-11-20T09:00:00+08:00')
        with self.assertRaises(ValueError):
            cell(field, 'tomorrow')


class ResolveTest(unittest.TestCase):
    def setUp(self):
        self.versions = [
            {'version': 'A', 'effective_at': '2026-11-17T16:00:00+00:00', 'issued_seq': 1, 'params': {}},
            {'version': 'B', 'effective_at': '2026-11-20T04:00:00+00:00', 'issued_seq': 1, 'params': {}},
            {'version': 'C', 'effective_at': '2026-11-20T04:00:00+00:00', 'issued_seq': 2, 'params': {}},
        ]

    def test_effective_at_arrival(self):
        self.assertEqual(resolve(self.versions, '2026-11-19T00:00:00+00:00')['version'], 'A')
        self.assertIsNone(resolve(self.versions, '2026-11-17T15:59:59+00:00'))

    def test_same_moment_unique_by_issued_seq(self):
        self.assertEqual(resolve(self.versions, '2026-11-20T04:00:00+00:00')['version'], 'C')
        self.assertIsNone(find_overlap(self.versions))

    def test_overlap_when_moment_and_seq_clash(self):
        dup = self.versions + [
            {'version': 'D', 'effective_at': '2026-11-20T04:00:00+00:00', 'issued_seq': 1, 'params': {}}]
        self.assertIsNotNone(find_overlap(dup))


class AnalyzeTest(unittest.TestCase):
    def test_scores_split_by_rule_version(self):
        result = analyze(demo_rows(), snapshot(0, 1))
        scores = result['tables'][1]['rows']
        self.assertEqual([row['rule_version'] for row in scores], ['R-20261118-A', 'R-20261120-B'])
        self.assertEqual([row['letters'] for row in scores], [4, 3])
        detail = result['tables'][0]['rows']
        for row in detail:
            expect = scores[0]['macro_f1'] if row['rule_version'] == 'R-20261118-A' else scores[1]['macro_f1']
            self.assertEqual(row['batch_total'], expect)

    def test_snapshot_frozen_for_late_records(self):
        result = analyze(demo_rows(), snapshot(0))
        detail = result['tables'][0]['rows']
        self.assertTrue(all(row['rule_version'] == 'R-20261118-A' for row in detail))
        self.assertEqual(len(result['tables'][1]['rows']), 1)

    def test_rerun_is_idempotent(self):
        first = analyze(demo_rows(), snapshot(0, 1))
        second = analyze(demo_rows(), snapshot(0, 1))
        self.assertEqual(first['tables'][0]['rows'], second['tables'][0]['rows'])
        ids = [row['ticket_id'] for row in second['tables'][0]['rows']]
        self.assertEqual(len(ids), len(set(ids)))

    def test_missing_rule_rejected(self):
        with self.assertRaisesRegex(ValueError, '没有生效版本'):
            analyze(demo_rows(), snapshot(1))

    def test_overlapping_snapshot_rejected(self):
        snap = snapshot(0) + [dict(DEMO_RULES[0], version='R-DUP')]
        with self.assertRaisesRegex(ValueError, '版本重叠'):
            analyze(demo_rows(), snap)

    def test_empty_snapshot_rejected(self):
        with self.assertRaisesRegex(ValueError, '规则快照'):
            analyze(demo_rows(), [])


if __name__ == '__main__':
    unittest.main()
