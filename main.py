import requests
import pandas as pd
from ics import Calendar, Event
from datetime import datetime, timedelta
import os
import pytz

# --- 🌍 用户配置区域 (修改这里) ---
# 尝试从环境变量获取，如果本地跑没有环境变量，就用后面的默认值（方便你本地测试）
LATITUDE = float(os.environ.get("USER_LAT", 30.27)) 
LONGITUDE = float(os.environ.get("USER_LON", 120.15))
TIMEZONE = "Asia/Shanghai" # 时区

# 阈值设置
LEVELS = [
    (35, "🌲 纯净空气", "空气极佳，强烈建议户外活动！(PM2.5 < 35)"),
    (75, "🧘 适宜出行", "空气良好，可以正常安排行程。(PM2.5 < 75)"),
]

def get_air_quality():
    """获取 Open-Meteo 的欧洲空气模型数据"""
    print("📡 正在连接气象卫星...")
    url = "https://air-quality-api.open-meteo.com/v1/air-quality"
    params = {
        "latitude": LATITUDE,
        "longitude": LONGITUDE,
        "hourly": "pm2_5",
        "timezone": TIMEZONE,
        "past_days": 0,
        "forecast_days": 7 
    }
    response = requests.get(url, params=params)
    response.raise_for_status()
    data = response.json()
    
    hourly = data['hourly']
    df = pd.DataFrame({
        'time': pd.to_datetime(hourly['time']),
        'pm25': hourly['pm2_5']
    })

    # --- 🧹 修复补丁: 数据清洗区域 ---
    # 1. 强制将 PM2.5 转为数字，遇到读不懂的怪数据直接变成 NaN (空值)
    df['pm25'] = pd.to_numeric(df['pm25'], errors='coerce')
    
    # 2. 只有当 PM2.5 是数字时才保留，删除所有空行
    # (这一步专门解决 '<=' not supported 报错)
    df.dropna(subset=['pm25'], inplace=True)
    
    print(f"✅ 获取成功！清洗后剩余 {len(df)} 条有效数据")
    return df

def generate_ics(df):
    """生成日历文件"""
    cal = Calendar()
    cal.creator = "Windy-Like Air Calendar"
    
    current_event = None
    
    for index, row in df.iterrows():
        pm_val = row['pm25']
        current_time = row['time'].tz_localize(TIMEZONE) 
        
        matched_level = None
        for threshold, title, desc in LEVELS:
            if pm_val <= threshold:
                matched_level = (title, desc)
                break 
        
        if current_event:
            if matched_level and current_event['title'] == matched_level[0]:
                current_event['end'] = current_time + timedelta(hours=1)
            else:
                e = Event()
                e.name = current_event['title']
                e.begin = current_event['start']
                e.end = current_event['end']
                e.description = current_event['desc']
                cal.events.add(e)
                current_event = None
                
                if matched_level:
                    current_event = {
                        'start': current_time,
                        'end': current_time + timedelta(hours=1),
                        'title': matched_level[0],
                        'desc': matched_level[1]
                    }
        else:
            if matched_level:
                current_event = {
                    'start': current_time,
                    'end': current_time + timedelta(hours=1),
                    'title': matched_level[0],
                    'desc': matched_level[1]
                }
    
    if current_event:
        e = Event()
        e.name = current_event['title']
        e.begin = current_event['start']
        e.end = current_event['end']
        e.description = current_event['desc']
        cal.events.add(e)
        
    return cal

if __name__ == "__main__":
    os.makedirs("public", exist_ok=True)
    
    try:
        df = get_air_quality()
        
        print("📅 正在计算时间窗口...")
        cal = generate_ics(df)
        
        with open('public/air_quality.ics', 'w', encoding='utf-8') as f:
            f.write(cal.serialize())
            
        print("🎉 大功告成！日历文件已生成: public/air_quality.ics")
    except Exception as e:
        print(f"❌ 依然报错: {e}")
        # 打印更多错误细节方便调试
        import traceback
        traceback.print_exc()