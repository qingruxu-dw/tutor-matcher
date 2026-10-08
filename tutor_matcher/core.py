"""多格式本地解析：同义标签、内容识别与保守的价格归一化。"""
import re
import hashlib

DEFAULT_PROFILE = {
    "subjects": ["物理", "数学", "英语"],
    "grades": ["一年级", "二年级", "三年级", "四年级", "五年级", "六年级", "初一", "初二", "初三", "高一", "高二"],
    "min_hourly": 100, "accept_all": True,
    "origin": "暨南大学番禺校区", "max_minutes": 60,
}
# 同义字段只是一层快速识别；无标签消息按内容识别，不依赖固定行数。
FIELDS = {'上课地址':'address', '辅导科目':'subject_text', '学生情况':'student', '老师要求':'requirements', '上课时间':'schedule', '薪资价格':'price'}
ALIASES = {'address':['上课地址','地址','授课地址','地点','区域'],
           'subject_text':['辅导科目','科目','求教科目','课程'],
           'student':['学生情况','学员','学生','学员情况'],
           'requirements':['老师要求','教员要求','教师要求'],
           'schedule':['上课时间','时间','授课时间'],
           'price':['薪资价格','课酬','课时费','报酬','薪资','价格']}
SUBJECTS = ['语文','数学','英语','物理','化学','生物','历史','地理','政治']
GRADE_RE = r'[一二三四五六]年级|初[一二三]|高[一二三]|[小中大]班|[1-6]年级|初[1-3]|高[1-3]'
NUMBER = r'(?:\d+(?:\.\d+)?|[一二两三四五六])'
RANGE = r'(\d+(?:\.\d+)?)(?:\s*[-—~至]\s*(\d+(?:\.\d+)?))?'
ID_RE = r'[A-Za-z]{1,8}\d{3,}'


def number(value):
    return float({'一':1,'二':2,'两':2,'三':3,'四':4,'五':5,'六':6}.get(value,value))


def parse_one(raw):
    id_match = re.search(r'【(?:广州家教单|编号|订单编号)】\s*[:：]?\s*('+ID_RE+r')',raw)
    if not id_match:
        id_match = re.search(r'^\s*('+ID_RE+r')\s*$',raw,re.M)
    job = {'id':id_match.group(1) if id_match else 'AUTO-'+hashlib.sha256(raw.encode()).hexdigest()[:12],
           'raw':raw,'warnings':[], 'evidence':{}, 'unrecognized_lines':[]}
    if not id_match:
        job['warnings'].append('未提供编号，使用内容生成临时编号')
    for key in ALIASES:
        job[key] = ''
    field_lookup = {alias:key for key,aliases in ALIASES.items() for alias in aliases}
    current = None
    free_lines = []
    for line in raw.splitlines():
        line=line.strip()
        if not line or '#新单' in line or re.fullmatch(ID_RE,line):
            continue
        tagged = re.match(r'【([^】]+)】\s*[:：,，]?\s*(.*)',line)
        if not tagged:
            # 同时支持“科目：...”这样的普通标签。
            tagged = re.match(r'('+ '|'.join(map(re.escape,field_lookup)) + r')\s*[:：]\s*(.*)',line)
        if tagged:
            label,value = tagged.groups()
            if label in ['编号','订单编号','广州家教单']:
                current=None
                continue
            if label in field_lookup:
                current=field_lookup[label]
                job[current] = (job[current]+' '+value).strip().lstrip('#')
                job['evidence'].setdefault(current,[]).append(line)
                continue
            current=None
        if current and not tagged:
            job[current] = (job[current]+' '+line).strip()
            job['evidence'].setdefault(current,[]).append(line)
        else:
            free_lines.append(line)
    # 无标签内容可能同时含年级、性别、科目等，每行不必只归一类。
    for line in free_lines:
        keys=[]
        if re.search(r'课时费|课酬|报酬|薪资|老师报价|\d\s*/\s*(?:[\d.]*[hH]|小时|次)',line):
            keys.append('price')
        elif re.search(r'老师|教员|大学生|师范|相应专业|教学经验',line):
            keys.append('requirements')
        elif re.search(r'周[一二三四五六日末天]|一周|两周|星期|晚上|上午|下午|\d+[：:]\d+',line):
            keys.append('schedule')
        elif re.search(r'区|街道|地铁|小区|花园|公馆|校区|教学楼|附近|国际|广州市|佛山市',line):
            keys.append('address')
        else:
            if re.search(GRADE_RE,line) or re.search(r'男孩|女孩|男生|女生',line):
                keys.append('student')
            if any(x in line for x in SUBJECTS) or re.search(r'语数英|全科|辅导作业|作业辅导|陪读',line):
                keys.append('subject_text')
        if not keys:
            job['unrecognized_lines'].append(line)
        for key in keys:
            job[key]=(job[key]+' '+line).strip().lstrip('#')
            job['evidence'].setdefault(key,[]).append(line)
    subject=job['subject_text']
    job['subjects']=[x for x in SUBJECTS if x in subject]
    if '语数英' in subject:
        job['subjects']=list(dict.fromkeys(['语文','数学','英语']+job['subjects']))
    job['split_subjects']=bool(re.search(r'分开|分科|各科分别',subject))
    job['all_subjects']=bool(re.search(r'全科|作业辅导|辅导作业|陪写作业',subject+' '+job['requirements']))
    job['companion']= '陪读' in subject
    grades=re.findall(GRADE_RE,subject+' '+job['student'])
    numeral={'1':'一','2':'二','3':'三','4':'四','5':'五','6':'六'}
    job['grades']=list(dict.fromkeys(''.join(numeral.get(c,c) for c in g) for g in grades))
    timing=job['schedule']+' '+job['price']
    duration=re.search(r'(?:一次|一节课|每次|周末)\s*(?:最少|至少)?\s*('+NUMBER+r')(?:\s*[-—~至]\s*('+NUMBER+r'))?\s*个?\s*(?:小时|[hH])',timing)
    job['duration_min']=number(duration.group(1)) if duration else None
    job['duration_max']=number(duration.group(2) or duration.group(1)) if duration else None
    job['duration_is_minimum']=bool(duration and re.search(r'最少|至少',duration.group(0)))
    if job['duration_is_minimum']:
        job['duration_max']=None
    if not duration and re.search(r'各\s*'+NUMBER+r'\s*小时',timing):
        job['warnings'].append('多个科目各自课时明确，不能直接视为单次总时长')
    price=job['price']
    job['hourly_min']=job['hourly_max']=None
    job['price_status']='unknown'
    hourly=re.search(RANGE+r'\s*元?\s*(?:/\s*(?:[hH]|小时)|(?:每|一)小时|元?\s*每小时)',price)
    per_hours=re.search(RANGE+r'\s*元?\s*/\s*('+NUMBER+r')\s*(?:[hH]|小时)',price)
    per_session=re.search(RANGE+r'\s*元?\s*(?:/\s*次|每次)',price)
    if hourly:
        job['hourly_min']=float(hourly.group(1))
        job['hourly_max']=float(hourly.group(2) or hourly.group(1))
        job['price_status']='hourly'
    elif per_hours:
        hours=number(per_hours.group(3))
        if hours>0:
            job['hourly_min']=float(per_hours.group(1))/hours
            job['hourly_max']=float(per_hours.group(2) or per_hours.group(1))/hours
            job['price_status']='converted'
            job['warnings'].append('按指定小时数报价已折算为时薪')
    elif per_session and job['duration_min'] and job['duration_max']:
        job['hourly_min']=float(per_session.group(1))/job['duration_max']
        job['hourly_max']=float(per_session.group(2) or per_session.group(1))/job['duration_min']
        job['price_status']='converted'
        job['warnings'].append('按次价格已按课时折算')
    elif re.search(r'报价|面议|带价',price):
        job['price_status']='negotiable'
        job['warnings'].append('老师报价或面议，时薪待确认')
    else:
        job['warnings'].append('价格单位或课时不明确，请确认')
    for label,key in FIELDS.items():
        if not job[key]:
            job['warnings'].append(label+'未识别或未提供')
    if job['companion']:
        job['warnings'].append('陪读的辅导范围未明确，不能等同于全科授课')
    if job['split_subjects']:
        job['warnings'].append('分科授课，可按可教科目申请；需确认对应科目报酬')
    if job['unrecognized_lines']:
        job['warnings'].append('有未归类内容，见解析核对区')
    job['fingerprint']=hashlib.sha256(re.sub(r'\s+','',raw).encode()).hexdigest()
    return job


def split_blocks(text):
    lines=text.splitlines()
    groups=[]
    current=[]
    has_fields=False
    def flush():
        nonlocal current,has_fields
        if current:
            content='\n'.join(current).strip()
            if content:
                groups.append(content)
        current=[]
        has_fields=False
    for line in lines:
        stripped=line.strip()
        if not stripped:
            # 空行可能只是排版。仅当下一个编号/科目出现时切单。
            current.append(line)
            continue
        start_id=bool(re.match(r'【广州家教单】',stripped) or re.fullmatch(ID_RE,stripped))
        start_subject=bool(re.match(r'【(?:科目|辅导科目|求教科目)】',stripped))
        if '#新单' in stripped:
            flush()
            continue
        if start_id and any(x.strip() for x in current):
            flush()
        elif start_subject and has_fields:
            flush()
        current.append(line)
        if start_subject:
            has_fields=True
        if re.match(r'【(?:编号|订单编号)】',stripped):
            flush()
    flush()
    return [g for g in groups if re.search(r'【|'+ID_RE+r'|年级|初[一二三]|高[一二三]|课时费',g)]


def parse_batch(text):
    jobs,by_id,duplicates=[],{},0
    for block in split_blocks(text):
        job=parse_one(block)
        if not any(job[k] for k in ALIASES):
            continue
        if job['id'] in by_id:
            existing=by_id[job['id']]
            if any(v['fingerprint']==job['fingerprint'] for v in existing['versions']):
                duplicates+=1
            else:
                existing['versions'].append(job)
                existing['warnings'].append('同编号内容不同，保留版本；需核实，未覆盖原记录')
        else:
            job['versions']=[dict(job)]
            jobs.append(job)
            by_id[job['id']]=job
    return jobs,duplicates

def match(job, profile):
    rejects, pending, reasons = [], [], []
    if job["all_subjects"]:
        if not profile["accept_all"]:
            rejects.append("不接受全科或作业辅导")
        else:
            pending.append("全科或作业辅导的具体范围需确认")
    elif job.get('companion'):
        pending.append('陪读范围与理科要求需确认')
    elif not job["subjects"]:
        pending.append("科目待确认")
    else:
        missing = set(job["subjects"]) - set(profile["subjects"])
        if job.get('split_subjects'):
            overlap=set(job['subjects']) & set(profile['subjects'])
            if overlap:
                reasons.append('可申请分科：'+'、'.join(sorted(overlap)))
                pending.append('分科安排与对应报酬需确认')
            else:
                rejects.append('分科需求中没有可教科目')
        elif missing:
            rejects.append("要求科目超出可教范围：" + "、".join(sorted(missing)))
        else:
            reasons.append("科目符合")
    if not job["grades"]:
        pending.append("年级待确认")
    elif any(g not in profile["grades"] for g in job["grades"]):
        rejects.append("包含不接受的年级：" + "、".join(g for g in job["grades"] if g not in profile["grades"]))
    else:
        reasons.append("年级符合")
    low, high = job["hourly_min"], job["hourly_max"]
    if low is None:
        pending.append('报酬需报价或面议确认' if job.get('price_status')=='negotiable' else '时薪单位待确认')
    elif high < profile["min_hourly"]:
        rejects.append(f"时薪上限{high:g}元，低于最低{profile['min_hourly']:g}元")
    elif low < profile["min_hourly"]:
        pending.append("报酬范围跨越最低时薪，需要议价确认")
    else:
        reasons.append("报酬符合")
    if len(job["versions"]) > 1:
        pending.append("同编号存在不同版本")
    if job["requirements"]:
        pending.append("教师要求需自行核对：" + job["requirements"])
    pending.append(f"地铁单程是否≤{profile['max_minutes']}分钟待确认（尚未接入地图）")
    return {"status": "不符合" if rejects else "候选，待确认", "rejects": rejects, "pending": pending, "reasons": reasons}
