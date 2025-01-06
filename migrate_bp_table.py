import sqlite3

def migrate_bp_table():
    conn = sqlite3.connect('meter.db')
    cursor = conn.cursor()
    
    try:
        # 1. 创建临时表
        cursor.execute('''CREATE TABLE IF NOT EXISTS bp_records_temp
                         (id INTEGER PRIMARY KEY AUTOINCREMENT,
                          date TEXT NOT NULL,
                          medicinetaken BOOLEAN DEFAULT FALSE,
                          morning_high INTEGER,
                          morning_low INTEGER,
                          night_high INTEGER,
                          night_low INTEGER,
                          avg_high REAL,
                          avg_low REAL,
                          risk_level TEXT,
                          notes TEXT)''')
        
        # 2. 复制数据
        cursor.execute('''INSERT INTO bp_records_temp 
                         (id, date, medicinetaken, morning_high, morning_low, 
                          night_high, night_low, risk_level, notes)
                         SELECT id, date, medicinetaken, morning_high, morning_low,
                                night_high, night_low, risk_level, notes
                         FROM bp_records''')
        
        # 3. 删除旧表
        cursor.execute('DROP TABLE bp_records')
        
        # 4. 重命名新表
        cursor.execute('ALTER TABLE bp_records_temp RENAME TO bp_records')
        
        conn.commit()
        print("数据库迁移成功！")
        
    except Exception as e:
        print(f"迁移错误: {str(e)}")
        conn.rollback()
    finally:
        cursor.close()
        conn.close()

if __name__ == '__main__':
    migrate_bp_table() 