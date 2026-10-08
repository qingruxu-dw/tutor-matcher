import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import parse_batch, parse_one, match, DEFAULT_PROFILE

class SampleTests(unittest.TestCase):
    def setUp(self):
        text = (Path(__file__).resolve().parents[1] / 'samples.txt').read_text(encoding='utf-8')
        self.jobs, self.duplicates = parse_batch(text)
        self.by_id = {j['id']: j for j in self.jobs}

    def test_duplicates_and_changed_version(self):
        self.assertEqual(len(self.jobs), 7)
        self.assertEqual(self.duplicates, 2)
        self.assertEqual(len(self.by_id['G2026100701']['versions']), 2)
        self.assertIn('女老师', self.by_id['G2026100701']['versions'][0]['requirements'])
        self.assertNotIn('女老师', self.by_id['G2026100701']['versions'][1]['requirements'])

    def test_per_session_rate(self):
        j = self.by_id['G202609301']
        self.assertEqual(j['duration_min'], 2)
        self.assertEqual(j['hourly_min'], 60)
        self.assertEqual(j['subjects'], ['语文', '数学', '英语'])
        self.assertEqual(match(j, DEFAULT_PROFILE)['status'], '不符合')

    def test_ambiguous_price(self):
        j = self.by_id['G202609231']
        self.assertIsNone(j['hourly_min'])
        self.assertEqual(match(j, DEFAULT_PROFILE)['status'], '候选，待确认')

    def test_duration_chinese_numerals(self):
        j = self.by_id['G202609161']
        self.assertEqual(j['duration_min'], 2)
        self.assertEqual(j['hourly_min'], 120)
        self.assertEqual(match(j, DEFAULT_PROFILE)['status'], '候选，待确认')

    def test_salary_range_needs_confirmation(self):
        j = self.by_id['G202609174']
        result = match(j, DEFAULT_PROFILE)
        self.assertEqual(j['duration_max'], 3)
        self.assertEqual(result['status'], '候选，待确认')
        self.assertTrue(any('议价' in x for x in result['pending']))

    def test_mixed_grades(self):
        j = self.by_id['G202609274']
        self.assertEqual(j['grades'], ['二年级', '中班'])
        self.assertEqual(j['duration_min'], 1.5)
        self.assertEqual(match(j, DEFAULT_PROFILE)['status'], '不符合')

    def test_biology_and_grade_excluded(self):
        result = match(self.by_id['G2026100701'], DEFAULT_PROFILE)
        self.assertEqual(len(result['rejects']), 2)

    def test_hourly_chinese(self):
        self.assertEqual(self.by_id['G2026100702']['hourly_min'], 70)

    def test_per_session_duration_range(self):
        j = parse_one('【广州家教单】G1\n【辅导科目】：数学\n【学生情况】：初一\n【上课时间】：一次1.5-2小时\n【薪资价格】：200/次')
        self.assertEqual(j['hourly_min'], 100)
        self.assertAlmostEqual(j['hourly_max'], 200/1.5)

if __name__ == '__main__':
    unittest.main()
