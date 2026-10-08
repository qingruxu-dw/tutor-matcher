from pathlib import Path
import json
import sqlite3
import time
from datetime import datetime, timezone, timedelta
import hashlib
import html
import streamlit as st
from core import DEFAULT_PROFILE, parse_batch, match
from maps import geocode, routes_for_mode, MODES, MapError
from ranking import sort_records, SORT_OPTIONS

ROOT = Path(__file__).parent
st.set_page_config(page_title="家教单匹配助手", layout="wide")
st.markdown('<style>' + (ROOT/'style.css').read_text(encoding='utf-8') + '</style>', unsafe_allow_html=True)
st.markdown('<div class="tech-hero"><div class="tech-kicker">TUTOR MATCH / GUANGZHOU</div><h1>家教单匹配助手</h1><div class="tech-subtitle">把每一份机会，放进你的科目、时间与出行半径。</div></div>', unsafe_allow_html=True)

def cached_call(identity, call):
    cache = st.session_state.setdefault('map_cache', {})
    item = cache.get(identity)
    if item and time.monotonic() - item[0] < (30 if item[2] else 300):
        if item[2]:
            raise MapError(item[1])
        return item[1]
    try:
        value = call()
    except MapError as e:
        cache[identity] = (time.monotonic(), str(e), True)
        raise
    cache[identity] = (time.monotonic(), value, False)
    return value

# 同一会话缓存5分钟，切换Key也重新查询，不将密钥写入文件。
profile = dict(DEFAULT_PROFILE)
with st.sidebar:
    st.header("我的偏好")
    profile['origin'] = st.text_input('出发位置（建议填校门）', profile['origin'], key='origin_address')
    profile['subjects'] = st.multiselect('可教科目', ['语文','数学','英语','物理','化学','生物','历史','地理','政治'], profile['subjects'])
    profile['grades'] = st.multiselect('可教年级', ['小班','中班','大班'] + DEFAULT_PROFILE['grades'] + ['高三'], profile['grades'])
    profile['accept_all'] = st.checkbox('接受全科／作业辅导', True)
    profile['min_hourly'] = st.number_input('最低时薪（元）', min_value=0, value=100)
    profile['max_minutes'] = st.number_input('最长单程通勤（分钟）', min_value=1, value=60)
    mode = st.selectbox('交通方式', MODES, key='travel_mode')
    map_key = st.text_input('高德 Web服务 Key', type='password', key='map_key')
    st.caption('地址和坐标用于高德查询，Key不写入数据库。')
    date, departure = '', ''
    if mode in MODES[:3] and st.checkbox('指定公共交通出发日期和时间'):
        now = datetime.now(timezone(timedelta(hours=8)))
        date = st.date_input('出发日期', now.date()).isoformat()
        departure = st.time_input('出发时间', now.time().replace(second=0, microsecond=0)).strftime('%H:%M')
    if st.button('刷新路线数据'):
        st.session_state['map_cache'] = {}
    st.caption('输入修改后按回车或移开焦点，会自动查询。重复查询在本次会话缓存5分钟。')

credential = hashlib.sha256(map_key.strip().encode()).hexdigest()

def persist(widget_key, model_key):
    st.session_state[model_key] = st.session_state[widget_key]


def resolve_location(address, prefix):
    if not map_key.strip() or not address.strip():
        return {'point': None, 'points': [], 'error': ''}
    try:
        points = cached_call(('geo', credential, address), lambda: geocode(address, map_key))
    except MapError as e:
        return {'point': None, 'points': [], 'error': str(e)}
    token = hashlib.sha256((address + str(points)).encode()).hexdigest()[:16]
    model = prefix + '_location_' + token
    index = st.session_state.get(model + '_index', 0)
    if index >= len(points):
        index = 0
    point = points[index]
    coarse = str(point['level']) in ['国家','省','市','区县','乡镇','村庄','街道','道路','未知','']
    needs_confirm = coarse or len(points)>1
    confirmed = st.session_state.get(model + '_confirmed_' + str(index), False)
    return {'point': point if not needs_confirm or confirmed else None, 'points': points,
            'index': index, 'model': model, 'needs_confirm': needs_confirm, 'error': ''}


def location_controls(info):
    if info['error']:
        st.warning(info['error'])
    if not info['points']:
        return
    points, index, model = info['points'], info['index'], info['model']
    if len(points)>1:
        widget = model + '_index_widget'
        st.selectbox('地图识别位置', range(len(points)), index=index,
                     format_func=lambda i: points[i]['address'] + '｜' + str(points[i]['level']),
                     key=widget, on_change=persist, args=(widget, model + '_index'))
    st.caption('定位：' + points[index]['address'] + '｜' + str(points[index]['level']))
    if info['needs_confirm']:
        st.warning('地址范围较大或存在多个结果，请补充小区、校门或确认采用此定位点。')
        confirmation = model + '_confirmed_' + str(index)
        widget = confirmation + '_widget'
        st.checkbox('使用这个定位点估算通勤', value=st.session_state.get(confirmation, False),
                    key=widget, on_change=persist, args=(widget, confirmation))

with st.sidebar:
    origin_info = resolve_location(profile['origin'], 'origin')
    location_controls(origin_info)
    origin = origin_info['point']
    if not map_key.strip():
        st.info('填写Key后自动定位并查询。')

sample = (ROOT/'samples.txt').read_text(encoding='utf-8')
if 'raw_messages' not in st.session_state:
    st.session_state['raw_messages'] = sample
with st.expander('导入家教消息', expanded=True):
    raw = st.text_area('粘贴家教消息（支持不同标签及无标签逐行描述）', height=180, key='raw_messages')
jobs, duplicates = parse_batch(raw)
if raw and not jobs:
    st.warning('未能识别这批消息，请保留原文；可尝试在订单之间加空行，并反馈新的格式。')

records = []
# 先计算全部订单状态，再过滤和排序；地址与定位选择存在独立模型中，隐藏不会丢失。
for job in jobs:
    result = match(job, profile)
    address = st.session_state.get('address_model_' + job['id'], job['address'])
    destination_info = resolve_location(address, 'dest_' + job['id'])
    destination = destination_info['point']
    routes, route_error = None, ''
    if origin and destination and map_key.strip():
        origin_city = origin.get('city', '广州')
        destination_city = destination.get('city', '广州')
        identity = ('route', credential, origin['location'], destination['location'], mode, date, departure, origin_city, destination_city)
        try:
            with st.spinner('正在更新路线方案…'):
                routes = cached_call(identity, lambda: routes_for_mode(origin['location'], destination['location'], map_key, mode, date, departure, origin_city, destination_city))
        except MapError as e:
            route_error = str(e)
    if routes:
        fastest = routes[0]
        result['pending'] = [p for p in result['pending'] if '尚未接入地图' not in p]
        if fastest['minutes'] > profile['max_minutes']:
            result['status'] = '不符合'
            result['rejects'].append(f"预计通勤{fastest['minutes']:.1f}分钟，超出{profile['max_minutes']}分钟")
        else:
            result['reasons'].append('预计通勤在上限内')
    records.append({'job': job, 'result': result, 'routes': routes, 'address': address,
                    'destination_info': destination_info, 'route_error': route_error})

candidate_count = sum(r['result']['status']=='候选，待确认' for r in records)
columns = st.columns(4)
for col, label, value in zip(columns, ['订单总数', '候选待确认', '不符合', '重复消息'], [len(jobs), candidate_count, len(jobs)-candidate_count, duplicates]):
    col.metric(label, value)
left, right = st.columns([1.2, 1])
with left:
    view = st.radio('筛选订单', ['全部', '候选，待确认', '不符合'], horizontal=True, key='result_filter')
with right:
    sort_option = st.selectbox('展示优先级', SORT_OPTIONS, key='sort_priority')
st.caption('价格按明确时薪下限排序；未知时薪或通勤在对应排序维度中排后。次优先级用于首优先级相同的订单。')
visible = [r for r in records if view=='全部' or r['result']['status']==view]
visible = sort_records(visible, sort_option)
st.caption(f'当前展示 {len(visible)} 单 · {mode}')
if not visible:
    st.info('当前分类没有订单，可切换筛选或调整偏好。')

for record in visible:
    job, result, routes = record['job'], record['result'], record['routes']
    with st.container(border=True, key='order_' + job['id']):
        st.markdown('<div class="order-id">'+html.escape(job['id'])+'</div>', unsafe_allow_html=True)
        title_col, status_col = st.columns([3, 1])
        with title_col:
            st.subheader(job['subject_text'])
        with status_col:
            st.markdown('<span class="status-badge">'+html.escape(result['status'])+'</span>', unsafe_allow_html=True)
        low, high = job['hourly_min'], job['hourly_max']
        rate = '待确认' if low is None else (f'{low:g}' if low==high else f'{low:g}–{high:g}') + ' 元/小时'
        c1, c2, c3 = st.columns(3)
        c1.metric('时薪', rate)
        c2.metric('最快预计通勤', f"{routes[0]['minutes']:.1f} 分钟" if routes else '待确认')
        c3.metric('年级', ' / '.join(job['grades']) or '待确认')
        widget = 'addr_' + job['id']
        st.text_input('上课终点（可修改）', record['address'], key=widget,
                      on_change=persist, args=(widget, 'address_model_' + job['id']))
        location_controls(record['destination_info'])
        if record['route_error']:
            st.warning(record['route_error'])
        if routes:
            st.markdown('<div class="route-label">ROUTE / 最快方案推荐</div>', unsafe_allow_html=True)
            for i, route in enumerate(routes):
                label = f"方案{i+1}｜约{route['minutes']:.1f}分钟｜" + ('推荐' if i == 0 else '备选')
                with st.expander(label, expanded=i == 0):
                    st.write(' → '.join(route['lines']))
                    parts = []
                    if route['route_km'] is not None:
                        parts.append(f"路线距离{route['route_km']:.1f}公里")
                    if mode in MODES[:3]:
                        parts.extend([f"步行{route['walking_km']:.1f}公里", f"换乘{route['transfers']}次"])
                    st.caption('；'.join(parts))
                    for detail in route.get('details', []):
                        st.write('• ' + detail)
            st.caption('推荐为返回方案中的最短预计时间。打车不含叫车等待时间；实际交通状况可能不同。')
        elif routes == []:
            st.warning('没有返回当前方式的可用路线，通勤保持待确认。')
        else:
            st.caption('起终点定位就绪后自动查询通勤。')
        if result['rejects']:
            st.error('；'.join(result['rejects']))
        if result['reasons']:
            st.caption('已符合：' + '；'.join(result['reasons']))
        st.info('待确认：' + '；'.join(result['pending']))
        st.write('上课时间：' + job['schedule'])
        if job['warnings']:
            st.warning('；'.join(job['warnings']))
        with st.expander('核对识别结果与原文依据'):
            st.dataframe([{'字段':label, '识别内容':job.get(field,'')} for label,field in [('科目','subject_text'),('学生情况','student'),('地址','address'),('时间','schedule'),('教师要求','requirements'),('原始报价','price')]], hide_index=True)
            st.caption('缺失信息不补造；92学校、专业与学校优先要求保留原文，由你核对。')
            if job.get('unrecognized_lines'):
                st.write('未归类内容：')
                st.text('\n'.join(job['unrecognized_lines']))
            st.json(job.get('evidence',{}), expanded=False)
        with st.expander('查看原消息和版本'):
            st.text('\n\n——另一版本——\n\n'.join(v['raw'] for v in job['versions']))

if st.button("保存当前订单到本地数据库", disabled=not jobs):
    with sqlite3.connect(ROOT / "orders.db") as db:
        db.execute("CREATE TABLE IF NOT EXISTS versions (fingerprint TEXT PRIMARY KEY, order_id TEXT, payload TEXT)")
        for job in jobs:
            for version in job["versions"]:
                db.execute("INSERT OR IGNORE INTO versions VALUES (?, ?, ?)", (version["fingerprint"], version["id"], json.dumps(version, ensure_ascii=False)))
    st.success("已保存，重复版本不会重复写入。")
if st.checkbox("查看已保存订单"):
    with sqlite3.connect(ROOT / "orders.db") as db:
        db.execute("CREATE TABLE IF NOT EXISTS versions (fingerprint TEXT PRIMARY KEY, order_id TEXT, payload TEXT)")
        rows = db.execute("SELECT order_id, payload FROM versions ORDER BY rowid DESC").fetchall()
    st.write(f"已保存 {len(rows)} 个版本")
    for order_id, payload in rows:
        with st.expander(order_id):
            st.json(json.loads(payload))
st.download_button("下载本次解析结果（JSON）", json.dumps(jobs, ensure_ascii=False, indent=2), "orders.json", "application/json")
