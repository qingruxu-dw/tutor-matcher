import unittest
from unittest.mock import patch
from maps import summarize_transits, straight_distance, geocode, MapError, routes_for_mode, MODES

class MapTests(unittest.TestCase):
    def test_straight_distance(self):
        self.assertEqual(straight_distance('113,23', '113,23'), 0)
        self.assertAlmostEqual(straight_distance('0,0', '0,1'), 111.195, places=2)

    def test_subway_filter_and_units(self):
        subway = {'duration': '3000', 'walking_distance': '1200', 'segments': [{'bus': {'buslines': [{'type': '地铁线路', 'name': '测试线', 'distance': '15000'}]}}]}
        bus = {'duration': '1200', 'walking_distance': '100', 'segments': [{'bus': {'buslines': [{'type': '普通公交', 'name': '测试公交', 'distance': '5000'}]}}]}
        data = {'route': {'transits': [bus, subway]}}
        result = summarize_transits(data)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['minutes'], 50)
        self.assertEqual(result[0]['route_km'], 16.2)
        self.assertEqual(result[0]['walking_km'], 1.2)
        self.assertEqual(len(summarize_transits(data, False)), 2)

    def test_no_routes(self):
        self.assertEqual(summarize_transits({'route': {}}), [])

    @patch('maps.request')
    def test_other_city_not_accepted(self, request):
        request.return_value = {'geocodes': [{'city': '深圳市', 'location': '114,22'}]}
        with self.assertRaises(MapError):
            geocode('同名地点', 'test')

    @patch('maps.request')
    def test_address_candidates_preserved(self, request):
        request.return_value = {'geocodes': [{'city': '广州市', 'location': '113,23', 'level': '街道', 'formatted_address': '测试街道'}]}
        self.assertEqual(geocode('测试', 'test')[0]['level'], '街道')

    @patch('maps.request')
    def test_bus_strategy_and_date(self, request):
        request.return_value = {'route': {'transits': []}}
        routes_for_mode('113,23', '114,23', 'test', MODES[2], '2026-10-08', '19:00')
        path, params, key = request.call_args.args
        self.assertEqual(params['strategy'], 5)
        self.assertEqual(params['date'], '2026-10-08')
        self.assertEqual(params['time'], '19:00')

    @patch('maps.request')
    def test_walking_and_driving_sort_by_time(self, request):
        request.return_value = {'route': {'paths': [{'duration':'3600','distance':'8000','steps':[]}, {'duration':'1800','distance':'9000','steps':[]}]}}
        routes = routes_for_mode('113,23', '114,23', 'test', MODES[4])
        self.assertEqual(routes[0]['minutes'], 30)
        self.assertEqual(routes[0]['route_km'], 9)
        self.assertEqual(request.call_args.args[1]['strategy'], 10)
        routes_for_mode('113,23', '114,23', 'test', MODES[3])
        self.assertIn('walking', request.call_args.args[0])

    def test_recommend_public_transport_by_total_time(self):
        def route(seconds, distance):
            return {'duration':str(seconds),'walking_distance':'500','segments':[{'bus':{'buslines':[{'type':'普通公交','name':'测试公交','distance':str(distance),'departure_stop':{'name':'起站'},'arrival_stop':{'name':'终站'}}]}}]}
        result = summarize_transits({'route':{'transits':[route(3600,3000),route(1800,5000)]}},subway_only=False)
        self.assertEqual(result[0]['minutes'],30)
        self.assertEqual(result[0]['route_km'],5.5)
        self.assertIn('起站上车',result[0]['details'][0])

    def test_do_not_replace_alternative_line_keep_old_duration(self):
        data={'route':{'transits':[{'duration':'1000','walking_distance':'0','segments':[{'bus':{'buslines':[{'type':'普通公交','name':'公交','distance':'1000'},{'type':'地铁线路','name':'地铁','distance':'2000'}]}}]}]}}
        self.assertEqual(summarize_transits(data,subway_only=True),[])

    @patch('maps.request')
    def test_foshan_location_and_cross_city_route(self, request):
        request.return_value={'geocodes':[{'city':'佛山市','location':'113,23','level':'门牌号','formatted_address':'佛山市南海区测试'}]}
        point=geocode('南海区测试','test')[0]
        self.assertEqual(point['city'],'佛山市')
        self.assertEqual(request.call_args.args[1]['city'],'佛山')
        request.return_value={'route':{'transits':[]}}
        routes_for_mode('113,23','114,23','test',MODES[0],origin_city='广州市',destination_city='佛山市')
        self.assertEqual(request.call_args.args[1]['cityd'],'佛山市')
