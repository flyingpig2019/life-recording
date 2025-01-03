from flask import Flask, render_template, request, redirect, url_for, jsonify, send_file
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user, fresh_login_required
import sqlite3
from datetime import datetime, date, timedelta
import pyotp
import base64
import os
import io
import zipfile
import pytz
from dotenv import load_dotenv
from github_utils import push_db_updates
from db import get_db, init_casino_db, init_meter_db

# 设置东部时区
eastern = pytz.timezone('US/Eastern')

# 初始化数据库
init_casino_db()
init_meter_db()

def get_eastern_time():
    """获取东部时间"""
    return datetime.now(eastern)

def format_eastern_date(dt=None):
    """格式化东部时间日期"""
    if dt is None:
        dt = get_eastern_time()
    return dt.strftime('%Y-%m-%d')

# 加载环境变量（仅在本地开发时使用）
if os.path.exists('.env'):
    load_dotenv()

# 设置会话配置
class Config:
    PERMANENT_SESSION_LIFETIME = timedelta(days=7)  # 设置会话持续7天
    REMEMBER_COOKIE_DURATION = timedelta(days=7)    # 设置记住我cookie持续7天

def get_secret(key: str) -> str:
    """从环境变量或 /etc/secrets 获取密钥"""
    # 首先尝试从环境变量获取
    value = os.getenv(key)
    if value:
        return value
    
    # 如果环境变量不存在，尝试从 /etc/secrets 读取
    secret_path = f'/etc/secrets/{key}'
    if os.path.exists(secret_path):
        with open(secret_path, 'r') as f:
            return f.read().strip()
    
    raise ValueError(f"{key} not found in environment variables or /etc/secrets")

app = Flask(__name__)
app.secret_key = get_secret('FLASK_SECRET_KEY')
app.config.from_object(Config)  # 应用会话配置

# 初始化 Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# 获取 TOTP 密钥
TOTP_SECRET = get_secret('TOTP_SECRET')

# 生成 Google Authenticator 的二维码 URL
totp_uri = pyotp.totp.TOTP(TOTP_SECRET).provisioning_uri(
    name="grand.cayden@gmail.com",
    issuer_name="Danny's Monitor"
)

# 创建用户类
class User(UserMixin):
    def __init__(self, email):
        self.id = email

@login_manager.user_loader
def load_user(user_id):
    return User(user_id)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'GET':
        return render_template('login.html')
    
    if request.method == 'POST':
        email = request.form['email']
        code = request.form['code']
        
        if email != 'grand.cayden@gmail.com':
            return render_template('login.html', error='邮箱不正确')
        
        totp = pyotp.TOTP(TOTP_SECRET)
        try:
            if totp.verify(code, valid_window=1):
                user = User(email)
                login_user(user, remember=True)  # 启用"记住我"功能
                return redirect(url_for('landing'))
            else:
                return render_template('login.html', error='验证码不正确，请确保手机时间准确')
        except Exception as e:
            print(f"验证错误: {str(e)}")
            return render_template('login.html', error=f'验证失败: {str(e)}')
    
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

def init_db():
    conn = sqlite3.connect('casino.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS casino_records
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  date TEXT NOT NULL,
                  amount REAL NOT NULL,
                  notes TEXT,
                  net REAL)''')
    conn.commit()
        # Example of selecting records ordered by id in descending order
    c.execute("SELECT * FROM casino_records ORDER BY strftime('%Y-%m-%d', date) DESC")
    records = c.fetchall()  # Fetch all records in the specified order
    for record in records:
        print(record)  # Print the records (or handle them as needed)
    conn.close()

def calculate_net():
    conn = sqlite3.connect('casino.db')
    c = conn.cursor()
    c.execute('SELECT SUM(amount) FROM casino_records')
    total = c.fetchone()[0] or 0
    conn.close()
    return total

import sqlite3

def init_meter_db():
    conn = sqlite3.connect('meter.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS meter_records
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  date TEXT NOT NULL,
                  meter REAL NOT NULL,
                  usage REAL,
                  notes TEXT,
                  conedtesla REAL)''')
    conn.commit()

    # Example of selecting records ordered by id in descending order
    c.execute('SELECT * FROM meter_records ORDER BY id DESC')
    records = c.fetchall()  # Fetch all records in the specified order
    for record in records:
        print(record)  # Print the records (or handle them as needed)

    conn.close()

def calculate_usage(meter_value, date_value):
    conn = sqlite3.connect('meter.db')
    c = conn.cursor()
    # 获取在此日期之前的最后一条记录的电表读数
    c.execute('''SELECT meter FROM meter_records 
                 WHERE date < ? 
                 ORDER BY date DESC LIMIT 1''', (date_value,))
    last_record = c.fetchone()
    conn.close()
    
    if last_record:
        # 当前读数减去前一次读数得到用电量
        return round(meter_value - last_record[0], 2)
    return 0  # 如果是第一条记录，用电量为0

def update_existing_usage():
    conn = sqlite3.connect('meter.db')
    c = conn.cursor()
    
    # 获取所有记录并按日期排序
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

@app.route('/')
@login_required
def landing():
    return render_template('landing.html')

@app.route('/casino')
@login_required
def casino():
    return render_template('casinoindex.html', current_date=datetime.now().strftime('%Y-%m-%d'))

@app.route('/submit', methods=['POST'])
@login_required
def submit():
    date = request.form['date']
    amount = float(request.form['amount'])
    notes = request.form['notes']
    
    conn = get_db()
    with conn.cursor() as cursor:
        # 计算当前记录的净收益（从第一条记录到当前记录的所有金额之和）
        cursor.execute('''SELECT COALESCE(SUM(amount), 0) 
                         FROM casino_records 
                         WHERE date <= %s''', (date,))
        net = cursor.fetchone()[0] + amount
        
        # 插入新记录
        cursor.execute('INSERT INTO casino_records (date, amount, net, notes) VALUES (%s, %s, %s, %s)',
                      (date, amount, net, notes))
        
        # 更新此记录之后的所有净收益
        cursor.execute('''UPDATE casino_records 
                         SET net = (SELECT SUM(amount) 
                                   FROM casino_records AS cr2 
                                   WHERE cr2.date <= casino_records.date)
                         WHERE date > %s''', (date,))
    
    conn.commit()
    conn.close()
    
    # 推送数据库更新到 GitHub
    success, message = push_db_updates()
    print(f"GitHub 推送结果: {success}, {message}")
    if not success:
        print(f"GitHub 推送失败: {message}")
    
    return redirect(url_for('casino'))

def get_records(page, per_page):
    conn = get_db('casino')
    cursor = conn.cursor()
    offset = (page - 1) * per_page
    cursor.execute('SELECT * FROM casino_records ORDER BY date DESC LIMIT ? OFFSET ?', (per_page, offset))
    records = cursor.fetchall()
    cursor.execute('SELECT COUNT(*) FROM casino_records')
    total_records = cursor.fetchone()[0]
    cursor.close()
    conn.close()
    return records, total_records

@app.route('/casino/detail')
@login_required
def casino_detail():
    page = request.args.get('page', 1, type=int)
    per_page = 25
    records, total_records = get_records(page, per_page)
    total_pages = (total_records + per_page - 1) // per_page
    return render_template('casinodetail.html', records=records, page=page, total_pages=total_pages)

@app.route('/edit/<int:id>', methods=['GET', 'POST'])
def edit(id):
    if request.method == 'GET':
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM casino_records WHERE id = ?', (id,))
        record = cursor.fetchone()
        cursor.close()
        conn.close()
        return render_template('casinoedit.html', record=record, format_eastern_date=format_eastern_date)
    else:
        date = request.form['date']
        amount = float(request.form['amount'])
        notes = request.form['notes']
        
        conn = get_db()
        cursor = conn.cursor()
        
        # 获取当前记录的金额
        cursor.execute('SELECT amount FROM casino_records WHERE id = ?', (id,))
        old_amount = cursor.fetchone()[0]
        
        # 更新记录
        cursor.execute('''UPDATE casino_records 
                         SET date = ?, amount = ?, notes = ?
                         WHERE id = ?''', (date, amount, notes, id))
        
        # 更新此记录之后的所有净收益
        cursor.execute('''UPDATE casino_records 
                         SET net = net + ? - ?
                         WHERE id >= ?''', (amount, old_amount, id))
        
        conn.commit()
        cursor.close()
        conn.close()
        
        # 推送数据库更新到 GitHub
        print("\n正在推送更新到 GitHub...")
        success, message = push_db_updates()
        if success:
            print(f"GitHub 推送成功: {message}")
        else:
            print(f"GitHub 推送失败: {message}")
        
        return redirect(url_for('detail'))

@app.route('/remove/<int:id>')
def remove(id):
    conn = get_db()
    with conn.cursor() as cursor:
        # 删除记录
        cursor.execute('DELETE FROM casino_records WHERE id = %s', (id,))
        
        # 更新所有记录的净收益
        cursor.execute('''UPDATE casino_records 
                         SET net = (SELECT SUM(amount) 
                                   FROM casino_records AS cr2 
                                   WHERE cr2.date <= casino_records.date)''')
    
    conn.commit()
    conn.close()
    return redirect(url_for('detail'))

@app.route('/total', methods=['GET', 'POST'])
def total():
    current_date = date.today()
    
    if request.method == 'POST':
        start_date = request.form['start_date']
        end_date = request.form['end_date']
    else:
        # 默认显示当月数据
        start_date = current_date.replace(day=1).strftime('%Y-%m-%d')
        end_date = current_date.strftime('%Y-%m-%d')
    
    conn = sqlite3.connect('casino.db')
    c = conn.cursor()
    
    # 计算总盈利（正值）
    c.execute('''SELECT SUM(amount) 
                FROM casino_records 
                WHERE amount > 0 
                AND date BETWEEN ? AND ?''', (start_date, end_date))
    total_win = c.fetchone()[0] or 0
    
    # 计算总亏损（负值）
    c.execute('''SELECT SUM(amount) 
                FROM casino_records 
                WHERE amount < 0 
                AND date BETWEEN ? AND ?''', (start_date, end_date))
    total_loss = c.fetchone()[0] or 0
    
    # 计算总收益
    total = total_win + total_loss
    
    # 格式化数字显示
    total_win = round(total_win, 2)
    total_loss = round(total_loss, 2)
    total = round(total, 2)
    
    conn.close()
    
    return render_template('casinototal.html',
                         total=total,
                         total_win=total_win,
                         total_loss=total_loss,
                         start_date=start_date,
                         end_date=end_date)

@app.route('/electricity')
def electricity():
    return render_template('electricityindex.html', current_date=datetime.now().strftime('%Y-%m-%d'))

@app.route('/electricity/submit', methods=['POST'])
def electricity_submit():
    date = request.form['date']
    meter = float(request.form['meter'])
    notes = request.form['notes']
    conedtesla = float(request.form['conedtesla']) if request.form['conedtesla'] else 0
    
    print(f"\n[{format_eastern_date()}] 正在添加电表记录...")
    print(f"日期: {date}")
    print(f"电表读数: {meter}")
    print(f"电费金额: {conedtesla}")
    print(f"备注: {notes}")
    
    conn = get_db()
    with conn.cursor() as cursor:
        # 获取前一次的读数
        cursor.execute('''SELECT meter FROM meter_records 
                        WHERE date < ? 
                        ORDER BY date DESC LIMIT 1''', (date,))
        last_record = cursor.fetchone()
        
        # 计算用电量
        usage = round(meter - last_record[0], 2) if last_record else 0
        print(f"计算得到用电量: {usage} kWh")
        
        # 插入新记录
        cursor.execute('''INSERT INTO meter_records 
                        (date, meter, usage, notes, conedtesla) 
                        VALUES (?, ?, ?, ?, ?)''',
                    (date, meter, usage, notes, conedtesla))
    
    conn.commit()
    conn.close()
    print("数据库更新成功!")
    
    # 推送数据库更新到 GitHub
    print("\n正在推送更新到 GitHub...")
    success, message = push_db_updates()
    if success:
        print(f"GitHub 推送成功: {message}")
    else:
        print(f"GitHub 推送失败: {message}")
    
    return redirect(url_for('electricity'))

def get_meter_records(page, per_page):
    conn = get_db('meter')
    cursor = conn.cursor()
    offset = (page - 1) * per_page
    cursor.execute('SELECT * FROM meter_records ORDER BY date DESC LIMIT ? OFFSET ?', (per_page, offset))
    records = cursor.fetchall()
    cursor.execute('SELECT COUNT(*) FROM meter_records')
    total_records = cursor.fetchone()[0]
    cursor.close()
    conn.close()
    return records, total_records

@app.route('/electricity/detail')
@login_required
def electricity_detail():
    page = request.args.get('page', 1, type=int)
    per_page = 25
    records, total_records = get_meter_records(page, per_page)
    total_pages = (total_records + per_page - 1) // per_page
    return render_template('meterdetail.html', records=records, page=page, total_pages=total_pages)

@app.route('/electricity/edit/<int:id>', methods=['GET', 'POST'])
def electricity_edit(id):
    if request.method == 'GET':
        conn = get_db('meter')
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM meter_records WHERE id = ?', (id,))
        record = cursor.fetchone()
        cursor.close()
        conn.close()
        return render_template('meteredit.html', record=record)
    else:
        date = request.form['date']
        meter = float(request.form['meter'])
        notes = request.form['notes']
        conedtesla = float(request.form['conedtesla']) if request.form['conedtesla'] else 0
        
        print(f"\n[{format_eastern_date()}] 正在更新电表记录 ID: {id}...")
        print(f"新数据 - 日期: {date}, 电表读数: {meter}, 电费金额: {conedtesla}")
        
        conn = get_db('meter')
        cursor = conn.cursor()
        
        # 更新当前记录
        cursor.execute('''UPDATE meter_records 
                         SET date = ?, meter = ?, notes = ?, conedtesla = ?
                         WHERE id = ?''', (date, meter, notes, conedtesla, id))
        
        print("记录更新成功!")
        
        # 更新所有用电量
        cursor.execute('SELECT id, date, meter FROM meter_records ORDER BY date')
        records = cursor.fetchall()
        
        print("正在重新计算所有用电量...")
        prev_meter = None
        for record in records:
            usage = 0 if prev_meter is None else round(record[2] - prev_meter, 2)
            cursor.execute('UPDATE meter_records SET usage = ? WHERE id = ?', 
                         (usage, record[0]))
            prev_meter = record[2]
        
        conn.commit()
        cursor.close()
        conn.close()
        print("所有用电量更新完成!")
        
        # 推送数据库更新到 GitHub
        print("\n正在推送更新到 GitHub...")
        success, message = push_db_updates()
        if success:
            print(f"GitHub 推送成功: {message}")
        else:
            print(f"GitHub 推送失败: {message}")
        
        return redirect(url_for('electricity_detail'))

@app.route('/electricity/remove/<int:id>')
def electricity_remove(id):
    conn = sqlite3.connect('meter.db')
    c = conn.cursor()
    c.execute('DELETE FROM meter_records WHERE id = ?', (id,))
    conn.commit()
    conn.close()
    return redirect(url_for('electricity_detail'))

@app.route('/electricity/chart')
def electricity_chart():
    return render_template('chart.html')

@app.route('/electricity/chart-data', methods=['POST'])
def electricity_chart_data():
    start_date = request.form['start_date']
    end_date = request.form['end_date']
    chart_type = request.form['chart_type']
    
    conn = get_db('meter')
    c = conn.cursor()
    c.execute('''SELECT date, usage, conedtesla 
                 FROM meter_records 
                 WHERE date BETWEEN ? AND ?
                 ORDER BY date''', (start_date, end_date))
    records = c.fetchall()
    conn.close()
    
    dates = [record[0] for record in records]
    meters = [record[1] for record in records]
    conedtesla = [record[2] for record in records]
    
    return jsonify({
        'dates': dates,
        'meters': meters,
        'conedtesla': conedtesla,
        'type': chart_type
    })

@app.route('/electricity/most', methods=['GET', 'POST'])
def electricity_most():
    if request.method == 'POST':
        start_date = request.form['start_date']
        end_date = request.form['end_date']
        conn = get_db('meter')
        cursor = conn.cursor()
        
        # 获取最高和最低用电量记录
        cursor.execute('''SELECT * FROM meter_records 
                         WHERE date BETWEEN ? AND ?
                         ORDER BY usage DESC LIMIT 5''', (start_date, end_date))
        highest = cursor.fetchall()
        
        cursor.execute('''SELECT * FROM meter_records 
                         WHERE date BETWEEN ? AND ?
                         ORDER BY usage ASC LIMIT 5''', (start_date, end_date))
        lowest = cursor.fetchall()
        
        # 计算平均用电量和总用电量
        cursor.execute('''SELECT AVG(usage), SUM(usage) FROM meter_records 
                         WHERE date BETWEEN ? AND ?''', (start_date, end_date))
        stats = cursor.fetchone()
        avg_usage = stats[0]
        total_usage = stats[1]
        
        conn.close()
        return render_template('most.html', 
                             highest=highest, 
                             lowest=lowest,
                             start_date=start_date,
                             end_date=end_date,
                             show_results=True,
                             avg_usage=avg_usage,
                             total_usage=total_usage)
    
    return render_template('most.html', 
                         start_date=date.today().strftime('%Y-%m-%d'),
                         end_date=date.today().strftime('%Y-%m-%d'),
                         show_results=False)

@app.route('/electricity/coned', methods=['GET', 'POST'])
def electricity_coned():
    if request.method == 'POST':
        start_date = request.form['start_date']
        end_date = request.form['end_date']
        
        conn = sqlite3.connect('meter.db')
        c = conn.cursor()
        c.execute('''SELECT SUM(conedtesla) 
                    FROM meter_records 
                    WHERE date BETWEEN ? AND ?''', (start_date, end_date))
        total = c.fetchone()[0] or 0
        conn.close()
        
        return render_template('coned.html', 
                             total=total,
                             start_date=start_date,
                             end_date=end_date,
                             show_results=True)
    
    return render_template('coned.html', 
                         show_results=False,
                         start_date=date.today().strftime('%Y-%m-%d'),
                         end_date=date.today().strftime('%Y-%m-%d'))

@app.route('/casino/chart')
def casino_chart():
    return render_template('casinochart.html')

@app.route('/casino/chart-data', methods=['POST'])
def casino_chart_data():
    start_date = request.form['start_date']
    end_date = request.form['end_date']
    chart_type = request.form['chart_type']
    
    conn = sqlite3.connect('casino.db')
    c = conn.cursor()
    c.execute('''SELECT date, amount 
                 FROM casino_records 
                 WHERE date BETWEEN ? AND ?
                 ORDER BY date''', (start_date, end_date))
    records = c.fetchall()
    conn.close()
    
    dates = [record[0] for record in records]
    amounts = [record[1] for record in records]
    
    return jsonify({
        'dates': dates,
        'amounts': amounts,
        'type': chart_type
    })

if __name__ == '__main__':
    init_db()
    init_meter_db()
    update_existing_usage()
    app.run(debug=True, host='0.0.0.0', port=5000) 