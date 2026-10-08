import unittest
from pathlib import Path
from core import parse_batch, parse_one, match, DEFAULT_PROFILE

class FlexibleTests(unittest.TestCase):
    def setUp(self):
        text=(Path(__file__).resolve().parents[1]/'samples_mixed.txt').read_text(encoding='utf-8')
        self.jobs,self.duplicates=parse_batch(text)
        self.by_id={j['id']:j for j in self.jobs}

    def test_all_eleven_recognized(self):
        self.assertEqual(len(self.jobs),11)
        self.assertEqual(self.duplicates,0)
        self.assertTrue(all(j['address'] and j['schedule'] and j['requirements'] and j['subject_text'] for j in self.jobs))

    def test_companion_not_invent_subjects(self):
        j=self.by_id['J3891008']
        self.assertEqual(j['grades'],['高二'])
        self.assertEqual(j['subjects'],[])
        self.assertTrue(j['companion'])
        self.assertEqual(j['hourly_min'],130)
        self.assertIn('92学校',j['requirements'])
        self.assertEqual(match(j,DEFAULT_PROFILE)['status'],'候选，待确认')

    def test_split_subjects_can_apply_english_math(self):
        j=self.by_id['J03811005']
        self.assertTrue(j['split_subjects'])
        self.assertEqual(j['subjects'],['语文','数学','英语'])
        result=match(j,DEFAULT_PROFILE)
        self.assertEqual(result['status'],'候选，待确认')
        self.assertTrue(any('分科' in s for s in result['pending']))

    def test_per_hours_prices(self):
        j=self.by_id['AC81002']
        self.assertEqual((j['hourly_min'],j['hourly_max']),(110,120))
        j=self.by_id['AC425001']
        self.assertEqual(j['hourly_min'],90)
        self.assertEqual(j['duration_min'],1.5)

    def test_bid_does_not_extract_duration_as_price(self):
        for identifier in ['AC714003','AC41003','AC69002']:
            j=self.by_id[identifier]
            self.assertIsNone(j['hourly_min'])
            self.assertEqual(j['price_status'],'negotiable')

    def test_minimum_duration_not_exact(self):
        j=self.by_id['J0323']
        self.assertEqual(j['duration_min'],2)
        self.assertIsNone(j['duration_max'])
        self.assertTrue(j['duration_is_minimum'])

    def test_multiple_subject_hours_not_single_session(self):
        j=self.by_id['AC69002']
        self.assertIsNone(j['duration_min'])
        self.assertIn('数学物理各2小时',j['schedule'])

    def test_mixed_original_and_new(self):
        root=Path(__file__).resolve().parents[1]
        jobs,duplicates=parse_batch((root/'samples.txt').read_text(encoding='utf-8')+'\n\n'+(root/'samples_mixed.txt').read_text(encoding='utf-8'))
        self.assertEqual(len(jobs),18)
        self.assertEqual(duplicates,2)

    def test_no_identifier_still_imported(self):
        jobs,_=parse_batch('【科目】：初二英语\n【课酬】：100/h\n【地址】：天河区测试小区')
        self.assertEqual(len(jobs),1)
        self.assertTrue(jobs[0]['id'].startswith('AUTO-'))

    def test_reordered_unlabelled_and_unknown_preserved(self):
        j=parse_one('AC99999\n课时费150/h\n周六下午\n英语\n初二女生\n天河区测试小区\n大学生女老师\n额外约定待沟通')
        self.assertEqual(j['subjects'],['英语'])
        self.assertEqual(j['grades'],['初二'])
        self.assertEqual(j['hourly_min'],150)
        self.assertIn('额外约定待沟通',j['unrecognized_lines'])
