"""高德 Web 服务适配，不输出密钥或请求 URL。"""
import json
import math
from urllib.parse import urlencode
from urllib.request import urlopen
from urllib.error import URLError

class MapError(Exception):
    pass

def request(path, params, key):
    if not key.strip():
        raise MapError('请先填写高德 Web服务 Key')
    url = 'https://restapi.amap.com' + path + '?' + urlencode(dict(params, key=key.strip(), output='JSON'))
    try:
        with urlopen(url, timeout=15) as response:
            data = json.load(response)
    except (URLError, TimeoutError, ValueError, OSError):
        raise MapError('地图请求失败，请检查网络或稍后重试') from None
    if data.get('status') != '1':
        raise MapError('高德接口未成功，错误码：' + str(data.get('infocode', '未知')) + '。请检查Key类型、服务权限和配额。')
    return data

def geocode(address, key):
    # 不把佛山需求强行定位在广州；南海、顺德作为城市检索提示，不代替接口核实。
    hint = '佛山' if any(s in address for s in ['佛山', '南海区', '顺德区', '禅城区']) else '广州'
    data = request('/v3/geocode/geo', {'address': address, 'city': hint}, key)
    items = []
    for g in data.get('geocodes', []):
        city = g.get('city')
        if city not in ['广州市', '佛山市']:
            continue
        loc = g.get('location', '')
        if loc:
            items.append({'address': g.get('formatted_address', address), 'location': loc, 'level': g.get('level', '未知'), 'city': city})
    if not items:
        raise MapError('未找到广州或佛山范围内的位置，请补充城市、区、小区或校门地址')
    return items

def straight_distance(origin, destination):
    lon1, lat1 = map(float, origin.split(','))
    lon2, lat2 = map(float, destination.split(','))
    a1, a2 = math.radians(lat1), math.radians(lat2)
    value = math.sin((a2-a1)/2)**2 + math.cos(a1)*math.cos(a2)*math.sin(math.radians(lon2-lon1)/2)**2
    return 6371 * 2 * math.asin(math.sqrt(min(1, max(0, value))))

def summarize_transits(data, subway_only=True, bus_only=False):
    results = []
    for transit in data.get('route', {}).get('transits', []):
        try:
            minutes = float(transit['duration']) / 60
            walking = float(transit.get('walking_distance') or 0)
        except (KeyError, ValueError, TypeError):
            continue
        modes, details, distance, has_other, has_subway = [], [], walking, False, False
        distance_valid = True
        for segment in transit.get('segments', []):
            walk = segment.get('walking') or {}
            if walk.get('distance'):
                details.append('步行约' + str(walk['distance']) + '米')
            if segment.get('railway'):
                has_other = True
                rail = segment['railway']
                if isinstance(rail, dict):
                    name = str(rail.get('name', '铁路'))
                    modes.append(name)
                    departure = (rail.get('departure_stop') or {}).get('name', '')
                    arrival = (rail.get('arrival_stop') or {}).get('name', '')
                    details.append(f'{departure}上车 → {name} → {arrival}下车')
                    try:
                        distance += float(rail['distance'])
                    except (KeyError, ValueError, TypeError):
                        distance_valid = False
            alternatives = segment.get('bus', {}).get('buslines', [])
            if not alternatives:
                continue
            # 保留接口原方案的首选线路，不用其他备选替换后沿用旧总时长。
            chosen = alternatives[0]
            if '地铁' not in str(chosen.get('type', '')):
                has_other = True
            else:
                has_subway = True
            modes.append(str(chosen.get('name', '未知线路')))
            departure = (chosen.get('departure_stop') or {}).get('name', '')
            arrival = (chosen.get('arrival_stop') or {}).get('name', '')
            details.append(f"{departure}上车 → {chosen.get('name', '未知线路')} → {arrival}下车")
            try:
                distance += float(chosen['distance'])
            except (KeyError, ValueError, TypeError):
                distance_valid = False
        if subway_only and (has_other or not modes):
            continue
        if bus_only and (has_subway or not modes):
            continue
        results.append({'minutes': minutes, 'walking_km': walking / 1000, 'route_km': distance / 1000 if distance_valid else None, 'lines': modes, 'details': details, 'transfers': max(0, len(modes)-1), 'cost': transit.get('cost')})
    return sorted(results, key=lambda x: x['minutes'])

def transit_routes(origin, destination, key, subway_only=True):
    data = request('/v3/direction/transit/integrated', {'origin': origin, 'destination': destination, 'city': '广州', 'cityd': '广州', 'strategy': 0, 'extensions': 'all'}, key)
    return summarize_transits(data, subway_only)

MODES = ['公共交通（公交＋地铁）', '地铁＋步行', '公交＋步行', '步行', '打车（驾车时间估算）']

def summarize_paths(data, driving=False):
    results = []
    for path in data.get('route', {}).get('paths', []):
        try:
            minutes = float(path['duration']) / 60
            distance = float(path['distance']) / 1000
        except (KeyError, TypeError, ValueError):
            continue
        steps = path.get('steps', [])
        details = [s['instruction'] for s in steps if s.get('instruction')]
        roads = list(dict.fromkeys(s['road'] for s in steps if s.get('road')))
        results.append({'minutes': minutes, 'route_km': distance, 'walking_km': 0 if driving else distance, 'transfers': 0, 'lines': roads or ['驾车' if driving else '步行'], 'details': details, 'cost': None})
    return sorted(results, key=lambda x: x['minutes'])

def routes_for_mode(origin, destination, key, mode, date='', time='', origin_city='广州', destination_city='广州'):
    params = {'origin': origin, 'destination': destination}
    if mode in MODES[:3]:
        params.update(city=origin_city, cityd=destination_city, strategy=5 if mode == MODES[2] else 0, extensions='all')
        if date and time:
            params.update(date=date, time=time)
        data = request('/v3/direction/transit/integrated', params, key)
        return summarize_transits(data, subway_only=mode == MODES[1], bus_only=mode == MODES[2])
    if mode == MODES[3]:
        return summarize_paths(request('/v3/direction/walking', params, key))
    if mode == MODES[4]:
        params.update(strategy=10, extensions='all')
        return summarize_paths(request('/v3/direction/driving', params, key), driving=True)
    raise MapError('不支持的交通方式')
