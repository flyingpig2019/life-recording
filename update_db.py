import sqlite3

def add_usage_column():
    conn = sqlite3.connect('meter.db')
    c = conn.cursor()
    
    # 添加 usage 列
    try:
        c.execute('ALTER TABLE meter_records ADD COLUMN usage REAL')
    except sqlite3.OperationalError:
        print("usage 列已存在")
    
    # 更新现有记录的 usage 值
    c.execute('SELECT id, date, meter FROM meter_records ORDER BY date')
    records = c.fetchall()
    
    prev_meter = None
    for record in records:
        # 当前读数减去前一次读数得到用电量
        usage = 0 if prev_meter is None else round(record[2] - prev_meter, 2)
        c.execute('UPDATE meter_records SET usage = ? WHERE id = ?', (usage, record[0]))
        prev_meter = record[2]
    
    conn.commit()
    conn.close()
    print("数据库更新完成")

if __name__ == "__main__":
    add_usage_column() 