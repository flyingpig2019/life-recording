import sqlite3

def get_db():
    """获取数据库连接"""
    return sqlite3.connect('casino.db')

def init_casino_db():
    """初始化赌场数据库"""
    conn = get_db()
    cursor = conn.cursor()
    
    # 创建赌场记录表
    cursor.execute('''CREATE TABLE IF NOT EXISTS casino_records
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      date TEXT NOT NULL,
                      amount REAL NOT NULL,
                      net REAL,
                      notes TEXT)''')
    
    conn.commit()
    cursor.close()
    conn.close()

def init_meter_db():
    """初始化电表数据库"""
    conn = sqlite3.connect('meter.db')
    cursor = conn.cursor()
    
    # 创建电表记录表
    cursor.execute('''CREATE TABLE IF NOT EXISTS meter_records
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      date TEXT NOT NULL,
                      meter REAL NOT NULL,
                      usage REAL,
                      notes TEXT,
                      conedtesla REAL)''')
    
    conn.commit()
    cursor.close()
    conn.close() 