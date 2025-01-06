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
import requests
from urllib.parse import urljoin
from functools import wraps
from flask import session, jsonify
import xlsxwriter
from io import BytesIO

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
    
    conn = get_db('casino')
    cursor = conn.cursor()
    try:
        # 获取前一条记录的净收益
        cursor.execute('''SELECT net FROM casino_records 
                         WHERE date < ? 
                         ORDER BY date DESC LIMIT 1''', (date,))
        last_record = cursor.fetchone()
        
        # 计算新的净收益
        net = amount + (last_record[0] if last_record else 0)
        
        # 插入新记录
        cursor.execute('''INSERT INTO casino_records (date, amount, net, notes)
                        VALUES (?, ?, ?, ?)''', 
                     (date, amount, net, notes))
        conn.commit()
    finally:
        cursor.close()
        conn.close()
    
    # 推送更新到GitHub
    push_db_updates()
    
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
        
        return redirect(url_for('casino_detail'))

@app.route('/remove/<int:id>')
@login_required
def remove(id):
    conn = get_db('casino')
    cursor = conn.cursor()
    try:
        # 获取要删除记录的日期
        cursor.execute('SELECT date FROM casino_records WHERE id=?', (id,))
        record = cursor.fetchone()
        if not record:
            # 如果记录不存在，直接返回
            return redirect(url_for('casino_detail'))
        
        # 删除记录
        cursor.execute('DELETE FROM casino_records WHERE id=?', (id,))
        
        # 重新计算所有记录的净收益
        cursor.execute('SELECT id, amount FROM casino_records ORDER BY date')
        records = cursor.fetchall()
        
        net = 0
        for record in records:
            net += record[1]  # 累加金额
            cursor.execute('UPDATE casino_records SET net=? WHERE id=?', (net, record[0]))
        
        conn.commit()
    except Exception as e:
        print(f"删除记录时发生错误: {str(e)}")
        conn.rollback()
    finally:
        cursor.close()
        conn.close()
    
    # 推送更新到GitHub
    push_db_updates()
    
    return redirect(url_for('casino_detail'))

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
@login_required
def electricity_submit():
    date = request.form['date']
    meter = float(request.form['meter'])
    notes = request.form['notes']
    conedtesla = request.form.get('conedtesla', type=float, default=0)
    
    conn = get_db('meter')
    cursor = conn.cursor()
    try:
        # 获取前一条记录的电表读数
        cursor.execute('''SELECT meter FROM meter_records 
                         WHERE date < ? 
                         ORDER BY date DESC LIMIT 1''', (date,))
        last_record = cursor.fetchone()
        
        # 计算用电量
        usage = round(meter - last_record[0], 2) if last_record else 0
        
        # 插入新记录
        cursor.execute('''INSERT INTO meter_records (date, meter, usage, notes, conedtesla)
                        VALUES (?, ?, ?, ?, ?)''', 
                     (date, meter, usage, notes, conedtesla))
        conn.commit()
    finally:
        cursor.close()
        conn.close()
    
    # 推送更新到GitHub
    push_db_updates()
    
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

@app.route('/sync-db', methods=['POST'])
def sync_db():
    try:
        # 从 .env 获取 GitHub 配置
        github_repo = os.getenv('GITHUB_REPO')
        if not github_repo:
            return jsonify({'success': False, 'message': '未找到 GitHub 仓库配置'})
        
        # 从 GitHub URL 提取用户名和仓库名
        parts = github_repo.split('/')
        username = parts[-2]
        repo = parts[-1]
        raw_base_url = f"https://raw.githubusercontent.com/{username}/{repo}/main/"
        
        print(f"使用仓库: {github_repo}")
        print(f"原始文件URL: {raw_base_url}")
        
        # 下载 casino.db
        casino_url = urljoin(raw_base_url, 'casino.db')
        print(f"正在从 {casino_url} 下载 casino.db...")
        
        # 添加认证头
        headers = {
            'Authorization': f'token {os.getenv("GITHUB_TOKEN")}'
        }
        casino_response = requests.get(casino_url, headers=headers)
        print(f"casino.db 响应状态码: {casino_response.status_code}")
        
        if casino_response.status_code == 200:
            print("casino.db 下载成功")
            try:
                with open('casino.db', 'wb') as f:
                    f.write(casino_response.content)
                print("casino.db 保存成功")
                print(f"casino.db 文件大小: {len(casino_response.content)} bytes")
            except Exception as e:
                print(f"casino.db 保存失败: {str(e)}")
        else:
            print(f"casino.db 下载失败: HTTP {casino_response.status_code}")
            print(f"错误响应: {casino_response.text}")
        
        # 下载 meter.db
        meter_url = urljoin(raw_base_url, 'meter.db')
        print(f"正在从 {meter_url} 下载 meter.db...")
        
        meter_response = requests.get(meter_url, headers=headers)
        print(f"meter.db 响应状态码: {meter_response.status_code}")
        
        if meter_response.status_code == 200:
            print("meter.db 下载成功")
            try:
                with open('meter.db', 'wb') as f:
                    f.write(meter_response.content)
                print("meter.db 保存成功")
                print(f"meter.db 文件大小: {len(meter_response.content)} bytes")
            except Exception as e:
                print(f"meter.db 保存失败: {str(e)}")
        else:
            print(f"meter.db 下载失败: HTTP {meter_response.status_code}")
            print(f"错误响应: {meter_response.text}")
        
        # 验证文件是否存在和大小
        if os.path.exists('casino.db'):
            print(f"验证: casino.db 存在，大小: {os.path.getsize('casino.db')} bytes")
        if os.path.exists('meter.db'):
            print(f"验证: meter.db 存在，大小: {os.path.getsize('meter.db')} bytes")
        
        success = all([
            casino_response.status_code == 200,
            meter_response.status_code == 200,
            os.path.exists('casino.db'),
            os.path.exists('meter.db')
        ])
        
        return jsonify({
            'success': success,
            'message': '数据库同步成功' if success else '数据库同步失败'
        })
    
    except Exception as e:
        print(f"发生异常: {str(e)}")
        return jsonify({
            'success': False,
            'message': '同步失败'
        })

def calculate_risk_level(high, low):
    """计算风险等级"""
    if high > 140 or low > 90:
        return 'high'
    elif high > 130 or low > 85:
        return 'medium'
    else:
        return 'normal'

def calculate_average(record):
    """计算平均血压"""
    morning_high = float(record['morning_high']) if record['morning_high'] else None
    night_high = float(record['night_high']) if record['night_high'] else None
    morning_low = float(record['morning_low']) if record['morning_low'] else None
    night_low = float(record['night_low']) if record['night_low'] else None
    
    avg_high = 0
    avg_low = 0
    
    # 计算高压平均值
    if morning_high is not None and night_high is not None:
        avg_high = (morning_high + night_high) / 2
    elif morning_high is not None:
        avg_high = morning_high
    elif night_high is not None:
        avg_high = night_high
    
    # 计算低压平均值
    if morning_low is not None and night_low is not None:
        avg_low = (morning_low + night_low) / 2
    elif morning_low is not None:
        avg_low = morning_low
    elif night_low is not None:
        avg_low = night_low
    
    return avg_high, avg_low

@app.route('/bp')
@login_required
def bp_index():
    return render_template('bpindex.html', current_date=datetime.now().strftime('%Y-%m-%d'))

@app.route('/bp/submit', methods=['POST'])
@login_required
def bp_submit():
    try:
        data = request.get_json()
        date = data['date']
        medicinetaken = data['medicinetaken']
        type = data['type']
        
        conn = get_db('meter')
        cursor = conn.cursor()
        
        try:
            # 检查是否已存在该日期的记录
            cursor.execute('SELECT * FROM bp_records WHERE date = ?', (date,))
            existing_record = cursor.fetchone()
            
            if type == 'morning':
                morning_high = data['morning_high']
                morning_low = data['morning_low']
                
                if existing_record:
                    # 更新现有记录的早晨数据，保持服药状态为True如果已设置
                    cursor.execute('''UPDATE bp_records 
                                    SET morning_high = ?, morning_low = ?, 
                                        medicinetaken = CASE 
                                            WHEN medicinetaken = 1 THEN 1 
                                            ELSE ? 
                                        END
                                    WHERE date = ?''',
                                 (morning_high, morning_low, medicinetaken, date))
                else:
                    # 创建新记录
                    cursor.execute('''INSERT INTO bp_records 
                                    (date, medicinetaken, morning_high, morning_low)
                                    VALUES (?, ?, ?, ?)''',
                                 (date, medicinetaken, morning_high, morning_low))
            elif type == 'night':
                night_high = data['night_high']
                night_low = data['night_low']
                
                if existing_record:
                    # 更新现有记录的晚间数据
                    cursor.execute('''UPDATE bp_records 
                                    SET night_high = ?, night_low = ?, medicinetaken = ?
                                    WHERE date = ?''',
                                 (night_high, night_low, medicinetaken, date))
                else:
                    # 创建新记录
                    cursor.execute('''INSERT INTO bp_records 
                                    (date, medicinetaken, night_high, night_low)
                                    VALUES (?, ?, ?, ?)''',
                                 (date, medicinetaken, night_high, night_low))
            elif type == 'medicine':
                if existing_record:
                    # 仅更新服药状态
                    cursor.execute('''UPDATE bp_records 
                                    SET medicinetaken = ?
                                    WHERE date = ?''',
                                  (medicinetaken, date))
                else:
                    # 创建新记录，仅包含服药状态
                    cursor.execute('''INSERT INTO bp_records 
                                    (date, medicinetaken)
                                    VALUES (?, ?)''',
                                  (date, medicinetaken))
            
            # 获取更新后的记录以计算平均值和风险等级
            cursor.execute('SELECT * FROM bp_records WHERE date = ?', (date,))
            record = cursor.fetchone()
            
            if record:
                record_dict = {
                    'morning_high': record[3],
                    'morning_low': record[4],
                    'night_high': record[5],
                    'night_low': record[6]
                }
                
                # 计算平均值和风险等级
                avg_high, avg_low = calculate_average(record_dict)
                risk_level = calculate_risk_level(
                    max(record[3] or 0, record[5] or 0),
                    max(record[4] or 0, record[6] or 0))
                
                # 更新记录
                cursor.execute('''UPDATE bp_records 
                                SET avg_high = ?, avg_low = ?, risk_level = ?
                                WHERE date = ?''',
                             (avg_high, avg_low, risk_level, date))
            
            conn.commit()
            
            # 推送更新到GitHub
            push_db_updates()
            
            return jsonify({'success': True, 'type': type})
            
        finally:
            cursor.close()
            conn.close()
            
    except Exception as e:
        print(f"Error in bp_submit: {str(e)}")
        return jsonify({'success': False, 'message': str(e)})

@app.route('/bp/detail')
@login_required
def bp_detail():
    page = request.args.get('page', 1, type=int)
    per_page = 25
    
    conn = get_db('meter')
    cursor = conn.cursor()
    
    try:
        # 获取总记录数
        cursor.execute('SELECT COUNT(*) FROM bp_records')
        total_records = cursor.fetchone()[0]
        total_pages = (total_records + per_page - 1) // per_page
        
        # 获取当前页的记录
        offset = (page - 1) * per_page
        cursor.execute('''SELECT * FROM bp_records 
                         ORDER BY date DESC 
                         LIMIT ? OFFSET ?''', 
                       (per_page, offset))
        records = cursor.fetchall()
        
        # 调试输出
        print("Records:", records)
        for record in records:
            print(f"Record {record[0]}: {record}")
        
        return render_template('bpdetail.html', 
                             records=records, 
                             page=page, 
                             total_pages=total_pages)
    finally:
        cursor.close()
        conn.close()

@app.route('/bp/edit/<int:id>', methods=['GET', 'POST'])
@login_required
def bp_edit(id):
    conn = get_db('meter')
    cursor = conn.cursor()
    
    try:
        if request.method == 'POST':
            date = request.form['date']
            medicinetaken = 'medicinetaken' in request.form
            morning_high = request.form.get('morning_high', type=int)
            morning_low = request.form.get('morning_low', type=int)
            night_high = request.form.get('night_high', type=int)
            night_low = request.form.get('night_low', type=int)
            
            # 计算平均值和风险等级
            record_dict = {
                'morning_high': morning_high,
                'morning_low': morning_low,
                'night_high': night_high,
                'night_low': night_low
            }
            avg_high, avg_low = calculate_average(record_dict)
            risk_level = calculate_risk_level(
                max(morning_high or 0, night_high or 0),
                max(morning_low or 0, night_low or 0)
            )
            
            # 更新记录
            cursor.execute('''UPDATE bp_records 
                            SET date=?, medicinetaken=?, 
                                morning_high=?, morning_low=?,
                                night_high=?, night_low=?,
                                avg_high=?, avg_low=?,
                                risk_level=?
                            WHERE id=?''',
                         (date, medicinetaken, morning_high, morning_low,
                          night_high, night_low, avg_high, avg_low,
                          risk_level, id))
            conn.commit()
            
            # 推送更新到GitHub
            push_db_updates()
            
            return redirect(url_for('bp_detail'))
        
        # GET 请求，获取记录
        cursor.execute('SELECT * FROM bp_records WHERE id=?', (id,))
        record = cursor.fetchone()
        if record is None:
            return redirect(url_for('bp_detail'))
        
        return render_template('bpedit.html', record=record)
        
    finally:
        cursor.close()
        conn.close()

@app.route('/bp/remove/<int:id>')
@login_required
def bp_remove(id):
    conn = get_db('meter')
    cursor = conn.cursor()
    
    try:
        cursor.execute('DELETE FROM bp_records WHERE id=?', (id,))
        conn.commit()
        
        # 推送更新到GitHub
        push_db_updates()
        
    finally:
        cursor.close()
        conn.close()
    
    return redirect(url_for('bp_detail'))

@app.route('/bp/chart')
@login_required
def bp_chart():
    return render_template('bpchart.html')

@app.route('/bp/chart-data')
@login_required
def bp_chart_data():
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    
    conn = get_db('meter')
    cursor = conn.cursor()
    
    try:
        cursor.execute('''SELECT date, 
                                 CASE 
                                     WHEN morning_high IS NOT NULL AND night_high IS NOT NULL 
                                     THEN (morning_high + night_high) / 2
                                     ELSE COALESCE(morning_high, night_high) 
                                 END as high,
                                 CASE 
                                     WHEN morning_low IS NOT NULL AND night_low IS NOT NULL 
                                     THEN (morning_low + night_low) / 2
                                     ELSE COALESCE(morning_low, night_low)
                                 END as low
                           FROM bp_records 
                           WHERE date BETWEEN ? AND ?
                           ORDER BY date''',
                        (start_date, end_date))
        records = cursor.fetchall()
        
        dates = [record[0] for record in records]
        high_pressures = [record[1] if record[1] else 0 for record in records]
        low_pressures = [record[2] if record[2] else 0 for record in records]
        
        return jsonify({
            'dates': dates,
            'high_pressures': high_pressures,
            'low_pressures': low_pressures
        })
        
    finally:
        cursor.close()
        conn.close()

@app.route('/bp/stats')
@login_required
def bp_stats():
    # 默认显示最近一周的统计
    stats = calculate_bp_stats('week')
    return render_template('bpaverage.html', stats=stats)

@app.route('/bp/stats-data')
@login_required
def bp_stats_data():
    period = request.args.get('period', 'week')
    stats = calculate_bp_stats(period)
    return jsonify(stats)

def calculate_bp_stats(period, start_date=None, end_date=None):
    conn = get_db('meter')
    cursor = conn.cursor()
    
    try:
        if period != 'custom':
            # 计算日期范围
            today = datetime.now().date()
            if period == 'week':
                start_date = (today - timedelta(days=7)).isoformat()
            elif period == 'month':
                start_date = (today - timedelta(days=30)).isoformat()
            else:  # year
                start_date = (today - timedelta(days=365)).isoformat()
            end_date = today.isoformat()
          
        # 获取指定时期的记录
        cursor.execute('''SELECT * FROM bp_records 
                         WHERE date BETWEEN ? AND ?
                         ORDER BY date''',
                       (start_date, end_date))
        records = cursor.fetchall()
        
        if not records:
            return {
                'avg_high': 0,
                'avg_low': 0,
                'max_high': 0,
                'max_low': 0,
                'min_high': 0,
                'min_low': 0,
                'medicine_rate': 0,
                'total_days': 0
            }
        
        # 计算统计数据
        highs = []
        lows = []
        medicine_taken = 0
        
        for record in records:
            if record[3]:  # morning_high
                highs.append(record[3])
            if record[5]:  # night_high
                highs.append(record[5])
            if record[4]:  # morning_low
                lows.append(record[4])
            if record[6]:  # night_low
                lows.append(record[6])
            if record[2]:  # medicinetaken
                medicine_taken += 1
        
        return {
            'avg_high': sum(highs) / len(highs) if highs else 0,
            'avg_low': sum(lows) / len(lows) if lows else 0,
            'max_high': max(highs) if highs else 0,
            'max_low': max(lows) if lows else 0,
            'min_high': min(highs) if highs else 0,
            'min_low': min(lows) if lows else 0,
            'medicine_rate': medicine_taken / len(records) if records else 0,
            'total_days': len(records)
        }
        
    finally:
        cursor.close()
        conn.close()

@app.route('/bp/export')
@login_required
def bp_export():
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    
    if not start_date:
        # 默认显示最近一个月的数据
        end_date = datetime.now().date().isoformat()
        start_date = (datetime.now() - timedelta(days=30)).date().isoformat()
    
    # 获取所有记录和统计数据
    stats = calculate_bp_stats('custom', start_date, end_date)
    
    conn = get_db('meter')
    cursor = conn.cursor()
    
    try:
        cursor.execute('''SELECT * FROM bp_records 
                         WHERE date BETWEEN ? AND ?
                         ORDER BY date DESC''',
                       (start_date, end_date))
        records = cursor.fetchall()
        
        return render_template('bpprint.html',
                             records=records,
                             stats=stats,
                             current_date=datetime.now().strftime('%Y-%m-%d'))
    finally:
        cursor.close()
        conn.close()

@app.route('/bp/export-excel')
@login_required
def bp_export_excel():
    # 创建一个内存中的Excel文件
    output = BytesIO()
    workbook = xlsxwriter.Workbook(output)
    worksheet = workbook.add_worksheet()
    
    # 添加标题行
    headers = ['日期', '服药情况', '早晨血压', '晚间血压', '平均值', '风险等级']
    for col, header in enumerate(headers):
        worksheet.write(0, col, header)
    
    # 获取数据
    conn = get_db('meter')
    cursor = conn.cursor()
    
    try:
        cursor.execute('SELECT * FROM bp_records ORDER BY date DESC')
        records = cursor.fetchall()
        
        # 写入数据
        for row, record in enumerate(records, 1):
            worksheet.write(row, 0, record[1])  # 日期
            worksheet.write(row, 1, "已服药" if record[2] else "未服药")  # 服药情况
            worksheet.write(row, 2, f"{record[3]}/{record[4]}" if record[3] else "--")  # 早晨血压
            worksheet.write(row, 3, f"{record[5]}/{record[6]}" if record[5] else "--")  # 晚间血压
            worksheet.write(row, 4, f"{record[7]}/{record[8]}" if record[7] else "--")  # 平均值
            risk_level = "正常" if record[9] == "normal" else "中等风险" if record[9] == "medium" else "高风险"
            worksheet.write(row, 5, risk_level)  # 风险等级
        
        workbook.close()
        
        # 设置响应头
        output.seek(0)
        return send_file(
            output,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            as_attachment=True,
            download_name=f'blood_pressure_records_{datetime.now().strftime("%Y%m%d")}.xlsx'
        )
        
    finally:
        cursor.close()
        conn.close()

if __name__ == '__main__':
    init_db()
    init_meter_db()
    update_existing_usage()
    app.run(debug=True, host='0.0.0.0', port=5000) 