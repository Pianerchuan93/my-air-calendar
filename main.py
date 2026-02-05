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

# --- ⚙️ 核心过滤配置 (新功能) ---
# 1. 时间屏蔽：0点到5点不显示
BLOCK_START_HOUR = 0  
BLOCK_END_HOUR = 5    

# 2. ⏳ 最短时长过滤 (关键修改)
# 只有连续持续 N 小时以上的时间段才显示。
# 建议设为 2，可以过滤掉很多零碎的 1 小时窗口，让日历更整洁。
MIN_DURATION_HOURS = 2 

# --- 🧪 阈值定义 ---
# 格式: (PM2.5, PM10, NO2, O3, 标题, 描述)
LEVELS = [
    (35, 50, 40, 100, "🌲 纯净空气", "空气极佳，快去跑步！(PM2.5<35)"),
    (75, 100, 80, 160, "🧘 适宜出行", "空气良好，放心出门。(PM2.5<75)"),
    (115, 150, 120, 200, "😐 还可以", "轻度污染，不戴口罩尚可忍受。(PM2.5<115)")
]

def get_air_quality():
    """获取全指标数据"""
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

    # 数据清洗
    cols = ['pm25', 'pm10', 'no2', 'o3']
    for col in cols:
        df[col] = pd.to_numeric(df[col], errors='coerce')
    df.dropna(subset=cols, inplace=True)
    return df

def generate_ics(df):
    cal = Calendar()
    cal.creator = "Smart Air Calendar"
    
    # 临时列表，用来存所有的候选事件
    potential_events = []
    current_event = None
    
    for index, row in df.iterrows():
        current_time = row['time'].tz_localize(TIMEZONE)
        vals = (row['pm25'], row['pm10'], row['no2'], row['o3'])

        # 1. 过滤深夜时间
        if BLOCK_START_HOUR <= current_time.hour < BLOCK_END_HOUR:
            if current_event:
                potential_events.append(current_event)
                current_event = None
            continue

        # 2. 判定等级
        matched_level = None
        for limit_pm25, limit_pm10, limit_no2, limit_o3, title, desc in LEVELS:
            if (vals[0] <= limit_pm25 and vals[1] <= limit_pm10 and 
                vals[2] <= limit_no2 and vals[3] <= limit_o3):
                matched_level = (title, desc)
                break 
        
        # 3. 合并逻辑
        if current_event:
            # 尝试延续
            if matched_level and current_event['title'] == matched_level[0]:
                current_event['end'] = current_time + timedelta(hours=1)
            else:
                # 结算上一个，开始下一个
                potential_events.append(current_event)
                current_event = None
                if matched_level:
                    current_event = create_event_dict(current_time, matched_level, vals)
        else:
            if matched_level:
                current_event = create_event_dict(current_time, matched_level, vals)
    
    # 循环结束，追加最后一个
    if current_event:
        potential_events.append(current_event)
        
    # --- 🧹 最终清洗：只保留长时间窗口 ---
    print(f"原始生成 {len(potential_events)} 个时间段，正在过滤短碎片...")
    count = 0
    for event_data in potential_events:
        # 计算时长 (小时)
        duration = (event_data['end'] - event_data['start']).total_seconds() / 3600
        
        # 只有时长 >= 设定值 (比如2小时) 才加入日历
        if duration >= MIN_DURATION_HOURS:
            e = Event()
            e.name = event_data['title']
            e.begin = event_data['start']
            e.end = event_data['end']
            e.description = event_data['desc']
            cal.events.add(e)
            count += 1
            
    print(f"✅ 最终保留 {count} 个优质长时段 (已过滤掉 < {MIN_DURATION_HOURS}小时的碎片)")
    return cal

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
        cal = generate_ics(df)
        with open('public/air_quality.ics', 'w', encoding='utf-8') as f:
            f.write(cal.serialize())
    except Exception as e:
        import traceback
        traceback.print_exc()
