import matplotlib.pyplot as plt
import pandas as pd
import os
import math
from datetime import datetime
import matplotlib.dates as mdates
from matplotlib.ticker import LinearLocator

GRAPH_DIR = "graphs"
os.makedirs(GRAPH_DIR, exist_ok=True)

speed_data_store = []

def set_speed_data(data):
    global speed_data_store
    speed_data_store = data

def create_speed_graph(minutes=10):
    global speed_data_store

    if not speed_data_store:
        return None, None

    now    = pd.to_datetime(datetime.now()).replace(second=0, microsecond=0)
    start  = now - pd.Timedelta(minutes=minutes)
    
    speed_data_store = [
        (ts, val) 
        for ts, val in speed_data_store
        if pd.to_datetime(ts).floor('min') >= start
    ]

    real = pd.DataFrame(speed_data_store, columns=['time', 'value'])
    real['time'] = pd.to_datetime(real['time']).dt.floor('min')
    real = real[(real['time'] >= start) & (real['time'] <= now)]

    real = real.groupby('time', as_index=True).sum()

    if minutes <= 30:
        freq = '1min'
        x_ticks = minutes + 1
    else:
        step = minutes // 30
        freq = f'{step}min'
        x_ticks = 30 + 1

    full_index = pd.date_range(start=start, end=now, freq='1min')
    df_min = real.reindex(full_index, fill_value=0)
    df_min.index.name = 'time'

    df = df_min 

    if minutes >= 60:
        factor = math.ceil(minutes / 30)
        freq = f'{factor}min'
        df = df.resample(freq).sum()

    fig, ax = plt.subplots(figsize=(12, 4))
    ax.plot(df.index, df['value'], marker='o', linestyle='-', color='blue')

    ax.set_title(f"Скорость за последние {minutes} мин")
    ax.set_xlabel("Время")
    ax.set_ylabel("Аккумуляторов/мин")
    ax.grid(True, axis='y', linestyle='--', alpha=0.5)

    ax.set_xlim(start, now)
    ax.xaxis.set_major_locator(LinearLocator(numticks=x_ticks))
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
    plt.xticks(rotation=90)

    ymax = df['value'].max()
    ax.set_ylim(0, ymax * 1.1 if ymax > 0 else 1)

    plt.tight_layout()

    ts = now.strftime("%Y%m%d_%H%M%S")
    img_path   = os.path.join(GRAPH_DIR, f"speed_{minutes}min_{ts}.png")
    plt.savefig(img_path)
    plt.close(fig)

    df_all_data = pd.DataFrame(speed_data_store, columns=['Время', 'Количество'])

    df_all_data = df_all_data.drop_duplicates()

    df_all_data['Время'] = pd.to_datetime(df_all_data['Время']).dt.strftime("%Y-%m-%d %H:%M")

    df_all_data['Тип_А'] = df_all_data['Количество']
    df_all_data['Тип_С'] = 0
    df_all_data['Тип_В'] = 0

    df_all_data = df_all_data.rename(columns={
        'Количество': 'Все типы'
    })

    df_all_data = df_all_data[['Время', 'Все типы', 'Тип_А', 'Тип_С', 'Тип_В']]

    ts = now.strftime("%H%M%S")
    excel_path = os.path.join(GRAPH_DIR, f"speed_ALL_DATA_{ts}.xlsx")
    df_all_data.to_excel(excel_path, index=False)

    return img_path, excel_path

