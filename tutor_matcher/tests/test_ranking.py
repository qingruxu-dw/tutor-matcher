import unittest
from ranking import sort_records, SORT_OPTIONS

def record(identifier, price, minutes):
    return {'job': {'id': identifier, 'hourly_min': price}, 'routes': [{'minutes': minutes}] if minutes is not None else None}

class RankingTests(unittest.TestCase):
    def setUp(self):
        self.rows = [record('unknown', None, None), record('A', 120, 50), record('B', 120, 30), record('C', 100, 20), record('D', 130, None)]

    def test_price_then_commute(self):
        self.assertEqual([r['job']['id'] for r in sort_records(self.rows, SORT_OPTIONS[0])], ['D', 'B', 'A', 'C', 'unknown'])

    def test_commute_then_price(self):
        self.assertEqual([r['job']['id'] for r in sort_records(self.rows, SORT_OPTIONS[1])], ['C', 'B', 'A', 'D', 'unknown'])

    def test_unknown_time_last_not_zero(self):
        rows = [record('missing', 200, None), record('known', 100, 90)]
        self.assertEqual(sort_records(rows, SORT_OPTIONS[3])[0]['job']['id'], 'known')
