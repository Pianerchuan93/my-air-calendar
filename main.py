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

# --- ⚙️ 时间配置 (已修改) ---
# 过滤掉深夜睡眠时间
# 修改：0点开始屏蔽，5点结束屏蔽。
# 效果：05:00 的数据就会开始显示了 (之前是 06:00)
BLOCK_START_HOUR = 0  
BLOCK_END_HOUR = 5    

# --- 🧪 阈值定义 (适配不戴口罩偏好) ---
# 格式: (PM2.5, PM10, NO2, O3, 标题, 描述)
LEVELS = [
    # Level 1: 纯净 (肺部SPA级)
    (35, 50, 40, 100, "🌲 纯净空气", "空气极佳，快去跑步！(PM2.5<35)"),
    
    # Level 2: 舒适 (不戴口罩无感级)
    (75, 100, 80, 160, "🧘 适宜出行", "空气良好，放心出门。(PM2.5<75)"),
    
    # Level 3: 勉强 (不戴口罩的肉体极限)
    (115, 150, 120, 200, "😐 还可以", "轻度污染，不戴口罩尚可忍受。(PM2.5<115)")
]

def get_air_quality():
    """获取全指标数据 (含臭氧)"""
    print(f"📡 正在获取全维度空气数据 (PM2.5, PM10, NO2, O3)...")
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

    # --- 数据清洗 ---
    cols = ['pm25', 'pm10', 'no2', 'o3']
    for col in cols:
        df[col] = pd.to_numeric(df[col], errors='coerce')
    
    df.dropna(subset=cols, inplace=True)
    
    print(f"✅ 获取成功！清洗后剩余 {len(df)} 条有效数据")
    return df

def generate_ics(df):
    cal = Calendar()
    cal.creator = "Smart Air Calendar"
    
    current_event = None
    
    for index, row in df.iterrows():
        current_time = row['time'].tz_localize(TIMEZONE)
        val_pm25 = row['pm25']
        val_pm10 = row['pm10']
        val_no2 = row['no2']
        val_o3 = row['o3']

        # --- 🌙 时间过滤逻辑 (屏蔽 00:00 - 05:00) ---
        # 如果当前小时 在 [0, 5) 之间，则跳过
        if BLOCK_START_HOUR <= current_time.hour < BLOCK_END_HOUR:
            if current_event:
                add_event_to_calendar(cal, current_event)
                current_event = None
            continue

        # --- 🔍 判定等级逻辑 ---
        matched_level = None
        for limit_pm25, limit_pm10, limit_no2, limit_o3, title, desc in LEVELS:
            if (val_pm25 <= limit_pm25 and 
                val_pm10 <= limit_pm10 and 
                val_no2 <= limit_no2 and 
                val_o3 <= limit_o3):
                
                matched_level = (title, desc)
                break 
        
        # --- 🔗 合并逻辑 ---
        if current_event:
            if matched_level and current_event['title'] == matched_level[0]:
                current_event['end'] = current_time + timedelta(hours=1)
            else:
                add_event_to_calendar(cal, current_event)
                current_event = None
                if matched_level:
                    current_event = create_event_dict(current_time, matched_level, val_pm25, val_pm10, val_no2, val_o3)
        else:
            if matched_level:
                current_event = create_event_dict(current_time, matched_level, val_pm25, val_pm10, val_no2, val_o3)
    
    if current_event:
        add_event_to_calendar(cal, current_event)
        
    return cal

def create_event_dict(time, level_info, pm25, pm10, no2, o3):
    return {
        'start': time,
        'end': time + timedelta(hours=1),
        'title': level_info[0],
        'desc': f"{level_info[1]}\n(PM2.5:{int(pm25)} | PM10:{int(pm10)} | NO2:{int(no2)} | O3:{int(o3)})"
    }

def add_event_to_calendar(cal, event_dict):
    e = Event()
    e.name = event_dict['title']
    e.begin = event_dict['start']
    e.end = event_dict['end']
    e.description = event_dict['desc']
    cal.events.add(e)

if __name__ == "__main__":
    os.makedirs("public", exist_ok=True)
    try:
        df = get_air_quality()
        cal = generate_ics(df)
        with open('public/air_quality.ics', 'w', encoding='utf-8') as f:
            f.write(cal.serialize())
        print("🎉 日历生成完毕！(0-5点屏蔽，05:00开始显示)")
    except Exception as e:
        import traceback
        traceback.print_exc()
