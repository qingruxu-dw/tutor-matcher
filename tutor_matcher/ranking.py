"""排序不把未知通勤当作零分钟，价格以明确的时薪下限为准。"""
SORT_OPTIONS = ['价格优先，其次通勤', '通勤优先，其次价格', '仅按价格从高到低', '仅按通勤从短到长']

def sort_records(records, option):
    def key(record):
        price = record['job']['hourly_min']
        minutes = record['routes'][0]['minutes'] if record.get('routes') else None
        p = (price is None, -price if price is not None else 0)
        t = (minutes is None, minutes if minutes is not None else 0)
        if option == SORT_OPTIONS[1]:
            return (*t, *p)
        if option == SORT_OPTIONS[2]:
            return p
        if option == SORT_OPTIONS[3]:
            return t
        return (*p, *t)
    return sorted(records, key=key)
