import sqlite3

def get_db(db_type='casino'):
    """获取数据库连接"""
    if db_type == 'casino':
        return sqlite3.connect('casino.db')
    elif db_type == 'meter':
        return sqlite3.connect('meter.db')
    else:
        raise ValueError("Invalid database type")

def init_casino_db():
    """初始化赌场数据库"""
    conn = get_db('casino')
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
    conn = get_db('meter')
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