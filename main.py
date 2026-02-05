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
FORECAST_DAYS = 7  # ✅ 已修改：预测改为 7 天

# --- 🌞 完美天气标准 (叠加在 Level 1 之上) ---
# 只有当空气是 Level 1，且同时满足以下条件时，升级为 "☀️ 完美户外"
PERFECT_CONDITION = {
    "temp_min": 10,      # 最低气温 (低于这个太冷)
    "temp_max": 28,      # 最高气温 (高于这个太热)
    "cloud_max": 50,     # 云量上限 (0=无云, 100=阴天, 50确保有阳光)
    "visibility_min": 10000 # 能见度下限 (米, 10km以上为通透)
}

# --- 🧪 阈值定义 ---

# 1. 🟢 Active 日历 (含完美时刻判断)
LEVELS_ACTIVE = [
    # Level 1: 纯净空气 (也是判定“完美户外”的基础层)
    (35, 50, 40, 100, "🌲 纯净空气", "空气极佳，强烈建议户外活动！(PM2.5<35)"),
    # Level 2: 适宜出行
    (75, 100, 80, 160, "🧘 适宜出行", "空气良好，放心出门。(PM2.5<75)")
]

# 2. 🟡 Warning 日历
LEVELS_WARNING = [
    (115, 150, 120, 200, "😷 刚需窗口", "轻度污染，刚需出门建议防护。(75 < PM2.5 < 115)")
]

def get_combined_data():
    """同时获取空气和天气数据并合并"""
    print(f"📡 正在获取 7 天数据 (空气 + 天气)...")
    
    # 1. 获取空气数据
    url_air = "https://air-quality-api.open-meteo.com/v1/air-quality"
    params_air = {
        "latitude": LATITUDE, "longitude": LONGITUDE,
        "hourly": "pm2_5,pm10,nitrogen_dioxide,ozone", 
        "timezone": TIMEZONE, "past_days": 0, "forecast_days": FORECAST_DAYS
    }
    res_air = requests.get(url_air, params=params_air)
    res_air.raise_for_status()
    df_air = pd.DataFrame(res_air.json()['hourly'])
    
    # 2. 获取天气数据 (气温、云量、能见度)
    url_weather = "https://api.open-meteo.com/v1/forecast"
    params_weather = {
        "latitude": LATITUDE, "longitude": LONGITUDE,
        "hourly": "temperature_2m,cloud_cover,visibility", 
        "timezone": TIMEZONE, "past_days": 0, "forecast_days": FORECAST_DAYS
    }
    res_weather = requests.get(url_weather, params=params_weather)
    res_weather.raise_for_status()
    df_weather = pd.DataFrame(res_weather.json()['hourly'])
    
    # 3. 合并数据 (基于时间)
    # 两个接口返回的时间字符串格式可能略有不同，统一转 datetime 后合并
    df_air['time'] = pd.to_datetime(df_air['time'])
    df_weather['time'] = pd.to_datetime(df_weather['time'])
    
    df = pd.merge(df_air, df_weather, on='time')
    
    # 清洗数据
    cols = ['pm25', 'pm10', 'nitrogen_dioxide', 'ozone', 'temperature_2m', 'cloud_cover', 'visibility']
    for col in cols:
        df[col] = pd.to_numeric(df[col], errors='coerce')
    df.dropna(subset=cols, inplace=True)
    
    return df

def generate_calendars(df):
    cal_active = Calendar(); cal_active.creator = "Air Active"
    cal_warning = Calendar(); cal_warning.creator = "Air Warning"
    
    events_active = []; events_warning = []
    curr_active = None; curr_warning = None
    
    for index, row in df.iterrows():
        current_time = row['time'].tz_localize(TIMEZONE)
        
        # 提取指标
        vals_air = (row['pm2_5'], row['pm10'], row['nitrogen_dioxide'], row['ozone'])
        vals_weather = (row['temperature_2m'], row['cloud_cover'], row['visibility']) # 气温, 云量, 能见度

        # 1. 过滤深夜
        if BLOCK_START_HOUR <= current_time.hour < BLOCK_END_HOUR:
            if curr_active: events_active.append(curr_active); curr_active = None
            if curr_warning: events_warning.append(curr_warning); curr_warning = None
            continue

        # --- Active 判定 ---
        match_act = None
        is_perfect = False # 标记是否是完美时刻
        
        for idx, (lim_p25, lim_p10, lim_no2, lim_o3, title, desc) in enumerate(LEVELS_ACTIVE):
            # 判断空气达标
            if (vals_air[0] <= lim_p25 and vals_air[1] <= lim_p10 and 
                vals_air[2] <= lim_no2 and vals_air[3] <= lim_o3):
                
                final_title = title
                final_desc = desc
                
                # 🔥 核心逻辑：如果是 Level 1 (纯净空气)，额外检查天气是否完美
                if idx == 0: # 0 代表 LEVELS_ACTIVE 里的第一项
                    temp, cloud, vis = vals_weather
                    if (PERFECT_CONDITION['temp_min'] <= temp <= PERFECT_CONDITION['temp_max'] and
                        cloud <= PERFECT_CONDITION['cloud_max'] and 
                        vis >= PERFECT_CONDITION['visibility_min']):
                        
                        is_perfect = True
                        final_title = "☀️ 完美户外" # 升级标题
                        # 升级描述
                        final_desc = (f"🌟 完美窗口！空气纯净，阳光明媚，温度舒适。\n"
                                      f"🌡️ {int(temp)}°C | ☁️ {int(cloud)}% | 👁️ {int(vis/1000)}km\n"
                                      f"{desc}")
                
                match_act = (final_title, final_desc)
                break
        
        # Active 合并逻辑
        if curr_active:
            # 只有标题完全一样才能合并 (意味着 纯净 和 完美 会被分开成两段，这是好事，突出了变化)
            if match_act and curr_active['title'] == match_act[0]:
                curr_active['end'] = current_time + timedelta(hours=1)
            else:
                events_active.append(curr_active)
                curr_active = None
                if match_act: curr_active = create_event_dict(current_time, match_act, vals_air)
        else:
            if match_act: curr_active = create_event_dict(current_time, match_act, vals_air)

        # --- Warning 判定 ---
        match_warn = None
        is_active_zone = (vals_air[0] <= 75 and vals_air[1] <= 100 and vals_air[2] <= 80 and vals_air[3] <= 160)
        
        if not is_active_zone:
            for lim_p25, lim_p10, lim_no2, lim_o3, title, desc in LEVELS_WARNING:
                if (vals_air[0] <= lim_p25 and vals_air[1] <= lim_p10 and 
                    vals_air[2] <= lim_no2 and vals_air[3] <= lim_o3):
                    match_warn = (title, desc)
                    break
        
        if curr_warning:
            if match_warn and curr_warning['title'] == match_warn[0]:
                curr_warning['end'] = current_time + timedelta(hours=1)
            else:
                events_warning.append(curr_warning)
                curr_warning = None
                if match_warn: curr_warning = create_event_dict(current_time, match_warn, vals_air)
        else:
            if match_warn: curr_warning = create_event_dict(current_time, match_warn, vals_air)

    if curr_active: events_active.append(curr_active)
    if curr_warning: events_warning.append(curr_warning)
    
    process_events_to_calendar(cal_active, events_active)
    process_events_to_calendar(cal_warning, events_warning)
    
    return cal_active, cal_warning

def process_events_to_calendar(cal, events):
    for e_data in events:
        start_dt = e_data['start']
        end_dt = e_data['end']
        duration = (end_dt - start_dt).total_seconds() / 3600
        
        if duration >= MIN_DURATION_HOURS:
            e = Event()
            t_start = start_dt.strftime('%H:%M')
            t_end = end_dt.strftime('%H:%M')
            # 24小时制标题
            e.name = f"[{t_start}-{t_end}] {e_data['title']}"
            e.begin = start_dt
            e.end = end_dt
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
        df = get_combined_data()
        cal_active, cal_warning = generate_calendars(df)
        
        with open('public/active.ics', 'w', encoding='utf-8') as f:
            f.write(cal_active.serialize())
        print("✅ active.ics 生成成功 (含完美天气判定)")
            
        with open('public/warning.ics', 'w', encoding='utf-8') as f:
            f.write(cal_warning.serialize())
        print("✅ warning.ics 生成成功")
            
    except Exception as e:
        import traceback
        traceback.print_exc()
