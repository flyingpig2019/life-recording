from flask import Flask, render_template, request, redirect, url_for
from flask import session, flash
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from functools import wraps
from pymongo import MongoClient
from datetime import datetime, timedelta
from dotenv import load_dotenv
import os
import pyotp
from pymongo.errors import PyMongoError, ServerSelectionTimeoutError
from bson.objectid import ObjectId
import signal
import sys
import platform

# 加载环境变量
load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('FLASK_SECRET_KEY')

# 设置会话持久化时间为7天
app.permanent_session_lifetime = timedelta(days=7)

# 设置登录管理器
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message = '请先登录'
login_manager.login_message_category = 'error'

class User(UserMixin):
    def __init__(self, email):
        self.id = email

@login_manager.user_loader
def load_user(user_id):
    if user_id == os.getenv('ADMIN_EMAIL'):
        return User(user_id)
    return None

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        totp_code = request.form['totp_code']
        
        if email != os.getenv('ADMIN_EMAIL'):
            return render_template('login.html', error="Invalid email")
        
        totp = pyotp.TOTP(os.getenv('TOTP_SECRET'))
        if totp.verify(totp_code):
            user = User(email)
            session.permanent = True  # 启用永久会话
            login_user(user)
            next_page = request.args.get('next')
            if not next_page or not next_page.startswith('/'):
                next_page = url_for('index')
            return redirect(next_page)
        else:
            return render_template('login.html', error="Invalid 2FA code")
    
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

# 全局变量
client = None
db = None
casino_collection = None
meter_collection = None

def force_exit(signum, frame):
    """强制退出程序"""
    print("\nForce stopping application...")
    if client:
        client.close()
        print("MongoDB connection closed")
    os._exit(1)

def signal_handler(signum, frame):
    """处理程序退出信号"""
    print("\nShutting down gracefully...")
    if client:
        client.close()
        print("MongoDB connection closed")
    try:
        sys.exit(0)
    except SystemExit:
        os._exit(1)

# 注册信号处理器
signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)
# 根据操作系统注册不同的强制退出信号
if platform.system() != 'Windows':
    # 在Unix系统上使用SIGQUIT (Ctrl+\)
    signal.signal(signal.SIGQUIT, force_exit)
else:
    # 在Windows系统上使用SIGBREAK (Ctrl+Break)
    signal.signal(signal.SIGBREAK, force_exit)

def init_db():
    global client, db, casino_collection, meter_collection
    if client:  # 如果已经有连接，先关闭
        client.close()
    try:
        client = MongoClient(uri)
        # 验证连接
        client.admin.command('ping')
        print("成功连接到MongoDB!")
        db = client.get_database('monitor')
        casino_collection = db['casino']
        meter_collection = db['meter']
    except (PyMongoError, ServerSelectionTimeoutError) as e:
        print(f"无法连接到MongoDB: {e}")
        raise

# MongoDB连接
uri = os.getenv('MONGODB_URI')
init_db()

# 注册模板过滤器
@app.template_filter('abs')
def abs_filter(n):
    return abs(n)

@app.route('/')
@login_required
def index():
    return render_template('index.html')

@app.route('/casino')
@login_required
def casino():
    current_date = datetime.now().strftime('%Y-%m-%d')
    return render_template('casinoindex.html', current_date=current_date)

@app.route('/submit_casino', methods=['POST'])
@login_required
def submit_casino():
    date = request.form['date']
    date_obj = datetime.strptime(date, '%Y-%m-%d')
    amount = float(request.form['amount'])
    note = request.form['note']
    
    # 获取前一条记录的净额
    previous_record = casino_collection.find_one(
        {'date': {'$lt': date_obj}},
        sort=[('date', -1)]
    )
    
    # 计算净额：前一条记录的净额 + 当前记录的金额
    previous_net = previous_record['net'] if previous_record else 0
    net = previous_net + amount
    
    casino_collection.insert_one({
        'date': date_obj,
        'amount': amount,
        'net': net,
        'note': note
    })
    
    # 更新后续记录的净额
    next_records = casino_collection.find(
        {'date': {'$gt': date_obj}},
        sort=[('date', 1)]
    )
    
    current_net = net
    for record in next_records:
        current_net = current_net + record['amount']  # 每条记录的净额都是前一条的净额加上当前金额
        casino_collection.update_one(
            {'_id': record['_id']},
            {'$set': {'net': current_net}}
        )
    
    return redirect(url_for('casino'))

@app.route('/casino_detail')
@login_required
def casino_detail():
    records = casino_collection.find().sort([('date', -1)])
    records = list(records)  # 将游标转换为列表
    return render_template('casinodetail.html', records=records)

@app.route('/edit_casino/<record_id>', methods=['GET', 'POST'])
@login_required
def edit_casino(record_id):
    if request.method == 'POST':
        date = request.form['date']
        date_obj = datetime.strptime(date, '%Y-%m-%d')
        amount = float(request.form['amount'])
        note = request.form['note']
        
        # 获取前一条记录的净额
        previous_record = casino_collection.find_one(
            {'date': {'$lt': date_obj}, '_id': {'$ne': ObjectId(record_id)}},
            sort=[('date', -1)]
        )
        
        # 计算净额：前一条记录的净额 + 当前记录的金额
        previous_net = previous_record['net'] if previous_record else 0
        net = previous_net + amount
        
        casino_collection.update_one(
            {'_id': ObjectId(record_id)},
            {'$set': {
                'date': date_obj,
                'amount': amount,
                'net': net,
                'note': note
            }}
        )
        
        # 更新后续记录的净额
        next_records = casino_collection.find(
            {'date': {'$gt': date_obj}},
            sort=[('date', 1)]
        )
        
        current_net = net
        for record in next_records:
            current_net = current_net + record['amount']  # 每条记录的净额都是前一条的净额加上当前金额
            casino_collection.update_one(
                {'_id': record['_id']},
                {'$set': {'net': current_net}}
            )
        
        return redirect(url_for('casino_detail'))
    
    record = casino_collection.find_one({'_id': ObjectId(record_id)})
    return render_template('edit_casino.html', record=record)

@app.route('/delete_casino/<record_id>')
@login_required
def delete_casino(record_id):
    # 获取要删除的记录
    record_to_delete = casino_collection.find_one({'_id': ObjectId(record_id)})
    if record_to_delete:
        # 删除记录
        casino_collection.delete_one({'_id': ObjectId(record_id)})
        
        # 更新后续记录的净额
        next_records = casino_collection.find(
            {'date': {'$gt': record_to_delete['date']}},
            sort=[('date', 1)]
        )
        
        # 获取前一条记录的净额作为基础
        previous_record = casino_collection.find_one(
            {'date': {'$lt': record_to_delete['date']}},
            sort=[('date', -1)]
        )
        
        current_net = previous_record['net'] if previous_record else 0
        
        # 更新所有后续记录的净额
        for record in next_records:
            current_net += record['amount']
            casino_collection.update_one(
                {'_id': record['_id']},
                {'$set': {'net': current_net}}
            )
    return redirect(url_for('casino_detail'))

@app.route('/meter')
@login_required
def meter():
    current_date = datetime.now().strftime('%Y-%m-%d')
    return render_template('meterindex.html', current_date=current_date)

@app.route('/submit_meter', methods=['POST'])
@login_required
def submit_meter():
    date = request.form['date']
    date_obj = datetime.strptime(date, '%Y-%m-%d')
    meter_read = float(request.form['meter_read'])
    tesla = float(request.form['tesla'])
    notes = request.form['notes']
    
    # 计算用量（如果有前一天的读数）
    previous_reading = meter_collection.find_one(
        {'date': {'$lt': date_obj}},
        sort=[('date', -1)]
    )
    
    usage = 0
    if previous_reading:
        usage = meter_read - previous_reading['meter_read']
    
    meter_collection.insert_one({
        'date': date_obj,
        'meter_read': meter_read,
        'usage': usage,
        'tesla': tesla,
        'notes': notes
    })
    return redirect(url_for('meter'))

@app.route('/meter_detail')
@login_required
def meter_detail():
    records = meter_collection.find().sort([('date', -1)])
    records = list(records)  # 将游标转换为列表
    return render_template('meterdetail.html', records=records)

@app.route('/edit_meter/<record_id>', methods=['GET', 'POST'])
@login_required
def edit_meter(record_id):
    if request.method == 'POST':
        date = request.form['date']
        date_obj = datetime.strptime(date, '%Y-%m-%d')
        meter_read = float(request.form['meter_read'])
        tesla = float(request.form['tesla'])
        notes = request.form['notes']
        
        # 重新计算用量
        previous_reading = meter_collection.find_one(
            {'date': {'$lt': date_obj}, '_id': {'$ne': ObjectId(record_id)}},
            sort=[('date', -1)]
        )
        
        usage = 0
        if previous_reading:
            usage = meter_read - previous_reading['meter_read']
        
        meter_collection.update_one(
            {'_id': ObjectId(record_id)},
            {'$set': {
                'date': date_obj,
                'meter_read': meter_read,
                'usage': usage,
                'tesla': tesla,
                'notes': notes
            }}
        )
        return redirect(url_for('meter_detail'))
    
    record = meter_collection.find_one({'_id': ObjectId(record_id)})
    return render_template('edit_meter.html', record=record)

@app.route('/delete_meter/<record_id>')
@login_required
def delete_meter(record_id):
    meter_collection.delete_one({'_id': ObjectId(record_id)})
    return redirect(url_for('meter_detail'))

@app.route('/meter_chart', methods=['GET', 'POST'])
@login_required
def meter_chart():
    if request.method == 'POST':
        start_date = datetime.strptime(request.form['start_date'], '%Y-%m-%d')
        end_date = datetime.strptime(request.form['end_date'], '%Y-%m-%d')
        chart_type = request.form['chart_type']
        
        records = list(meter_collection.find({
            'date': {
                '$gte': start_date,
                '$lte': end_date
            }
        }).sort('date', 1))
        
        dates = [r['date'].strftime('%Y-%m-%d') for r in records]
        usages = [r['usage'] for r in records]
        tesla_values = [r.get('tesla', 0) * 10 for r in records]
        
        if chart_type == 'line':
            chart_data = {
                'type': 'line',
                'data': {
                    'labels': dates,
                    'datasets': [
                        {
                            'label': '用电量 (kWh)',
                            'data': usages,
                            'borderColor': 'rgb(75, 192, 192)',
                            'tension': 0.1
                        },
                        {
                            'label': '特斯拉充电 (kWh)',
                            'data': tesla_values,
                            'borderColor': 'rgb(255, 99, 132)',
                            'tension': 0.1
                        }
                    ]
                }
            }
        elif chart_type == 'bar':
            chart_data = {
                'type': 'bar',
                'data': {
                    'labels': dates,
                    'datasets': [
                        {
                            'label': '家庭用电 (kWh)',
                            'data': [u - t for u, t in zip(usages, tesla_values)],
                            'backgroundColor': 'rgba(75, 192, 192, 0.2)',
                            'borderColor': 'rgb(75, 192, 192)',
                            'borderWidth': 1,
                            'order': 2
                        },
                        {
                            'label': '特斯拉充电 (kWh)',
                            'data': tesla_values,
                            'backgroundColor': 'rgba(255, 99, 132, 0.2)',
                            'borderColor': 'rgb(255, 99, 132)',
                            'borderWidth': 1,
                            'order': 1
                        }
                    ]
                },
                'options': {
                    'scales': {
                        'x': {
                            'stacked': True
                        },
                        'y': {
                            'stacked': True,
                            'beginAtZero': True,
                            'title': {
                                'display': True,
                                'text': '用电量 (kWh)'
                            }
                        }
                    }
                }
            }
        else:  # pie
            total_usage = sum(usages)
            total_tesla = sum(tesla_values)
            chart_data = {
                'type': 'pie',
                'data': {
                    'labels': ['家庭用电 (kWh)', '特斯拉充电 (kWh)'],
                    'datasets': [{
                        'data': [total_usage - total_tesla, total_tesla],
                        'backgroundColor': [
                            'rgba(75, 192, 192, 0.2)',
                            'rgba(255, 99, 132, 0.2)'
                        ],
                        'borderColor': [
                            'rgb(75, 192, 192)',
                            'rgb(255, 99, 132)'
                        ],
                        'borderWidth': 1
                    }]
                }
            }
        
        return render_template('meterchart.html', chart_data=chart_data)
    
    return render_template('meterchart.html')

@app.route('/meter_usage', methods=['GET', 'POST'])
@login_required
def meter_usage():
    if request.method == 'POST':
        start_date = datetime.strptime(request.form['start_date'], '%Y-%m-%d')
        end_date = datetime.strptime(request.form['end_date'], '%Y-%m-%d')
        
        # 获取时间范围内的总用电量
        records = list(meter_collection.find({
            'date': {
                '$gte': start_date,
                '$lte': end_date
            }
        }))
        total_usage = sum(r['usage'] for r in records)
        
        # 获取最高用电量记录
        highest_usage = list(meter_collection.find().sort('usage', -1).limit(5))
        
        # 获取最低用电量记录（排除用电量为0的记录）
        lowest_usage = list(meter_collection.find({'usage': {'$gt': 0}}).sort('usage', 1).limit(5))
        
        return render_template('metertotal.html', 
                             total_usage=total_usage,
                             highest_usage=highest_usage,
                             lowest_usage=lowest_usage)
    
    return render_template('metertotal.html')

@app.route('/tesla_total', methods=['GET', 'POST'])
@login_required
def tesla_total():
    if request.method == 'POST':
        start_date = datetime.strptime(request.form['start_date'], '%Y-%m-%d')
        end_date = datetime.strptime(request.form['end_date'], '%Y-%m-%d')
        
        records = list(meter_collection.find({
            'date': {
                '$gte': start_date,
                '$lte': end_date
            }
        }))
        
        total_tesla = sum(float(r.get('tesla', 0)) * 10 for r in records)  # 乘以10转换为kWh
        total_tesla = round(total_tesla, 2)  # 保留两位小数
        
        return render_template('teslatotal.html', total_tesla=total_tesla)
    
    return render_template('teslatotal.html', total_tesla=None)

@app.route('/casino_total', methods=['GET', 'POST'])
@login_required
def casino_total():
    if request.method == 'POST':
        start_date = datetime.strptime(request.form['start_date'], '%Y-%m-%d')
        end_date = datetime.strptime(request.form['end_date'], '%Y-%m-%d')
        
        records = casino_collection.find({
            'date': {
                '$gte': start_date,
                '$lte': end_date
            }
        })
        
        total_gain = sum(r['amount'] for r in records if r['amount'] > 0)
        records.rewind()
        total_loss = sum(r['amount'] for r in records if r['amount'] < 0)
        records.rewind()
        total_net = sum(r['amount'] for r in records)
        
        results = {
            'total_net': total_net,
            'total_gain': total_gain,
            'total_loss': total_loss
        }
        
        return render_template('casinototal.html', results=results)
    
    return render_template('casinototal.html')

@app.route('/casino_chart', methods=['GET', 'POST'])
@login_required
def casino_chart():
    if request.method == 'POST':
        start_date = datetime.strptime(request.form['start_date'], '%Y-%m-%d')
        end_date = datetime.strptime(request.form['end_date'], '%Y-%m-%d')
        chart_type = request.form['chart_type']
        
        records = list(casino_collection.find({
            'date': {
                '$gte': start_date,
                '$lte': end_date
            }
        }).sort('date', 1))
        
        dates = [r['date'].strftime('%Y-%m-%d') for r in records]
        amounts = [r['amount'] for r in records]
        nets = [r['net'] for r in records]
        
        if chart_type == 'line':
            chart_data = {
                'type': 'line',
                'data': {
                    'labels': dates,
                    'datasets': [
                        {
                            'label': '收益',
                            'data': amounts,
                            'tension': 0,
                            'borderWidth': 2,
                            'pointRadius': 5,
                            'pointHoverRadius': 7
                        }
                    ]
                },
                'options': {
                    'scales': {
                        'y': {
                            'title': {
                                'display': True,
                                'text': '金额 ($)'
                            },
                            'grid': {
                                'color': 'rgba(0, 0, 0, 0.1)',
                                'drawOnChartArea': True
                            },
                            'beginAtZero': True
                        },
                        'x': {
                            'title': {
                                'display': True,
                                'text': '日期'
                            }
                        }
                    },
                    'plugins': {
                        'annotation': {
                            'annotations': {
                                'line1': {
                                    'type': 'line',
                                    'yMin': 0,
                                    'yMax': 0,
                                    'borderColor': 'rgb(33, 150, 243)',
                                    'borderWidth': 2
                                }
                            }
                        }
                    }
                }
            }
        elif chart_type == 'bar':
            chart_data = {
                'type': 'bar',
                'data': {
                    'labels': dates,
                    'datasets': [{
                        'label': '收益',
                        'data': amounts,
                        'backgroundColor': [
                            'rgba(75, 192, 192, 0.2)' if amount > 0 
                            else 'rgba(255, 99, 132, 0.2)' 
                            for amount in amounts
                        ],
                        'borderColor': [
                            'rgb(75, 192, 192)' if amount > 0 
                            else 'rgb(255, 99, 132)' 
                            for amount in amounts
                        ],
                        'borderWidth': 1
                    }]
                }
            }
        else:  # pie
            gains = sum(amount for amount in amounts if amount > 0)
            losses = abs(sum(amount for amount in amounts if amount < 0))
            chart_data = {
                'type': 'pie',
                'data': {
                    'labels': ['收益', '损失'],
                    'datasets': [{
                        'data': [gains, losses],
                        'backgroundColor': [
                            'rgba(75, 192, 192, 0.2)',
                            'rgba(255, 99, 132, 0.2)'
                        ],
                        'borderColor': [
                            'rgb(75, 192, 192)',
                            'rgb(255, 99, 132)'
                        ],
                        'borderWidth': 1
                    }]
                }
            }
        
        return render_template('casinochart.html', chart_data=chart_data)
    
    return render_template('casinochart.html')

if __name__ == '__main__':
    app.run(debug=True, use_reloader=False, port=5000) 