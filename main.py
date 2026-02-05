import requests
import pandas as pd
from ics import Calendar, Event
from datetime import datetime, timedelta
import os
import pytz

# --- 🌍 用户配置区域 ---
LATITUDE = float(os.environ.get("USER_LAT", 31.23)) 
LONGITUDE = float(os.environ.get("USER_LON", 121.47))
TIMEZONE = "Asia/Shanghai"

# --- ⚙️ 核心过滤配置 ---
BLOCK_START_HOUR = 0  
BLOCK_END_HOUR = 5    
MIN_DURATION_HOURS = 2 

# --- 🧪 双重阈值定义 ---

# 1. 🟢 出行日历 (Active) - 纯享受型
# 逻辑：PM2.5 < 75。这是你平时默认开启的日历。
LEVELS_ACTIVE = [
    (35, 50, 40, 100, "🌲 纯净空气", "空气极佳，强烈建议户外活动！(PM2.5<35)"),
    (75, 100, 80, 160, "🧘 适宜出行", "空气良好，放心出门。(PM2.5<75)")
]

# 2. 🟡 刚需日历 (Warning) - 只有需要时才勾选
# 逻辑：75 < PM2.5 < 115。
# 只有在这个区间（轻度污染），才会出现在这个日历里。
# 超过 115 的严重污染，会被脚本直接丢弃，不显示在任何日历上。
LEVELS_WARNING = [
    # 唯一的等级：勉强可行
    # 这里的阈值 115 是上限。如果 PM2.5 是 150，这行代码会匹配失败，从而不生成任何事件。
    (115, 150, 120, 200, "😷 刚需窗口", "轻度污染，刚需出门建议防护。(75 < PM2.5 < 115)")
]

def get_air_quality():
    print(f"📡 正在获取数据...")
    url = "https://air-quality-api.open-meteo.com/v1/air-quality"
    params = {
        "latitude": LATITUDE,
        "longitude": LONGITUDE,
        "hourly": "pm2_5,pm10,nitrogen_dioxide,ozone", 
        "timezone": TIMEZONE,
        "past_days": 0,
        "forecast_days": 5
    }
    response = requests.get(url, params=params)
    response.raise_for_status()
    data = response.json()
    
    hourly = data['hourly']
    df = pd.DataFrame({
        'time': pd.to_datetime(hourly['time']),
        'pm25': hourly['pm2_5'],
        'pm10': hourly['pm10'],
        'no2': hourly['nitrogen_dioxide'],
        'o3': hourly['ozone']
    })

    cols = ['pm25', 'pm10', 'no2', 'o3']
    for col in cols:
        df[col] = pd.to_numeric(df[col], errors='coerce')
    df.dropna(subset=cols, inplace=True)
    return df

def generate_calendars(df):
    cal_active = Calendar()
    cal_active.creator = "Air Active"
    
    cal_warning = Calendar()
    cal_warning.creator = "Air Warning"
    
    # 临时存储
    events_active = []
    events_warning = []
    
    curr_active = None
    curr_warning = None
    
    for index, row in df.iterrows():
        current_time = row['time'].tz_localize(TIMEZONE)
        vals = (row['pm25'], row['pm10'], row['no2'], row['o3'])

        # 1. 过滤深夜
        if BLOCK_START_HOUR <= current_time.hour < BLOCK_END_HOUR:
            if curr_active: events_active.append(curr_active); curr_active = None
            if curr_warning: events_warning.append(curr_warning); curr_warning = None
            continue

        # --- Active 判定 ---
        match_act = None
        for lim_p25, lim_p10, lim_no2, lim_o3, title, desc in LEVELS_ACTIVE:
            if (vals[0] <= lim_p25 and vals[1] <= lim_p10 and 
                vals[2] <= lim_no2 and vals[3] <= lim_o3):
                match_act = (title, desc)
                break
        
        # Active 事件合并逻辑
        if curr_active:
            if match_act and curr_active['title'] == match_act[0]:
                curr_active['end'] = current_time + timedelta(hours=1)
            else:
                events_active.append(curr_active)
                curr_active = None
                if match_act: curr_active = create_event_dict(current_time, match_act, vals)
        else:
            if match_act: curr_active = create_event_dict(current_time, match_act, vals)

        # --- Warning 判定 (逻辑简化) ---
        match_warn = None
        # 先判断是不是已经属于 Active (好天气不用 Warning)
        is_active_zone = (vals[0] <= 75 and vals[1] <= 100 and vals[2] <= 80 and vals[3] <= 160)
        
        if not is_active_zone:
            # 只有不是好天气的时候，才去查是不是“勉强能行”
            # 如果 PM2.5 是 150，这里的判断 (150 <= 115) 会失败 -> match_warn 为 None
            for lim_p25, lim_p10, lim_no2, lim_o3, title, desc in LEVELS_WARNING:
                if (vals[0] <= lim_p25 and vals[1] <= lim_p10 and 
                    vals[2] <= lim_no2 and vals[3] <= lim_o3):
                    match_warn = (title, desc)
                    break
        
        # Warning 事件合并逻辑
        if curr_warning:
            if match_warn and curr_warning['title'] == match_warn[0]:
                curr_warning['end'] = current_time + timedelta(hours=1)
            else:
                events_warning.append(curr_warning)
                curr_warning = None
                if match_warn: curr_warning = create_event_dict(current_time, match_warn, vals)
        else:
            if match_warn: curr_warning = create_event_dict(current_time, match_warn, vals)

    # 循环结束结算
    if curr_active: events_active.append(curr_active)
    if curr_warning: events_warning.append(curr_warning)
    
    process_events_to_calendar(cal_active, events_active)
    process_events_to_calendar(cal_warning, events_warning)
    
    return cal_active, cal_warning

def process_events_to_calendar(cal, events):
    for e_data in events:
        duration = (e_data['end'] - e_data['start']).total_seconds() / 3600
        if duration >= MIN_DURATION_HOURS:
            e = Event()
            e.name = e_data['title']
            e.begin = e_data['start']
            e.end = e_data['end']
            e.description = e_data['desc']
            cal.events.add(e)

def create_event_dict(time, level_info, vals):
    return {
        'start': time,
        'end': time + timedelta(hours=1),
        'title': level_info[0],
        'desc': f"{level_info[1]}\n(PM2.5:{int(vals[0])} | PM10:{int(vals[1])} | NO2:{int(vals[2])} | O3:{int(vals[3])})"
    }

if __name__ == "__main__":
    os.makedirs("public", exist_ok=True)
    try:
        df = get_air_quality()
        cal_active, cal_warning = generate_calendars(df)
        
        with open('public/active.ics', 'w', encoding='utf-8') as f:
            f.write(cal_active.serialize())
        print("✅ 生成成功：active.ics (享受日历)")
            
        with open('public/warning.ics', 'w', encoding='utf-8') as f:
            f.write(cal_warning.serialize())
        print("✅ 生成成功：warning.ics (刚需日历)")
            
    except Exception as e:
        import traceback
        traceback.print_exc()
