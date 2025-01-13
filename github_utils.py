import os
from github import Github
from datetime import datetime, timedelta
import pytz
import sqlite3
import tempfile
import shutil
import time

def push_db_updates():
    """推送数据库更新到 GitHub"""
    try:
        # 获取 GitHub 凭据
        username = os.getenv('GITHUB_USERNAME')
        token = os.getenv('GITHUB_TOKEN')
        
        # 创建 GitHub 实例
        g = Github(token)
        
        # 获取仓库
        repo = g.get_user().get_repo('life-recording')
        
        # 获取东部时间
        eastern = pytz.timezone('US/Eastern')
        current_time = datetime.now(eastern)
        time_str = current_time.strftime('%Y-%m-%d %H:%M:%S EST')
        
        # 获取24小时前的时间
        yesterday = current_time - timedelta(days=1)
        
        def merge_db_updates(local_db_path, github_db_content, table_names):
            # 创建临时文件来保存 GitHub 的数据库
            with tempfile.NamedTemporaryFile(delete=False) as temp_file:
                temp_file.write(github_db_content)
                github_db_path = temp_file.name
            
            local_conn = None
            github_conn = None
            merged_conn = None
            
            try:
                # 等待数据库解锁（最多等待10秒）
                max_attempts = 10
                for attempt in range(max_attempts):
                    try:
                        # 连接数据库时启用超时和立即模式
                        local_conn = sqlite3.connect(local_db_path, timeout=5)
                        local_conn.execute('PRAGMA journal_mode=WAL')
                        local_conn.execute('PRAGMA busy_timeout=5000')
                        
                        github_conn = sqlite3.connect(github_db_path, timeout=5)
                        github_conn.execute('PRAGMA journal_mode=WAL')
                        github_conn.execute('PRAGMA busy_timeout=5000')
                        break
                    except sqlite3.OperationalError as e:
                        if attempt == max_attempts - 1:
                            raise
                        time.sleep(1)
                
                # 创建合并后的数据库
                merged_db_path = f"{local_db_path}_merged"
                merged_conn = sqlite3.connect(merged_db_path, timeout=5)
                merged_conn.execute('PRAGMA journal_mode=WAL')
                merged_conn.execute('PRAGMA busy_timeout=5000')
                
                for table in table_names:
                    # 获取表结构
                    cursor = github_conn.execute(f"SELECT sql FROM sqlite_master WHERE type='table' AND name='{table}'")
                    create_table_sql = cursor.fetchone()[0]
                    
                    # 在合并数据库中创建表
                    merged_conn.execute(create_table_sql)
                    merged_conn.commit()
                    
                    # 从 GitHub 数据库复制旧记录
                    cursor = github_conn.execute(f"SELECT * FROM {table}")
                    rows = cursor.fetchall()
                    if rows:
                        columns = ', '.join(['?' for _ in range(len(rows[0]))])
                        merged_conn.executemany(
                            f"INSERT OR IGNORE INTO {table} VALUES ({columns})",
                            rows
                        )
                        merged_conn.commit()
                    
                    # 从本地数据库更新/插入新记录
                    cursor = local_conn.execute(f"SELECT * FROM {table} WHERE date >= ?", 
                                                  (yesterday.strftime('%Y-%m-%d'),))
                    rows = cursor.fetchall()
                    if rows:
                        columns = ', '.join(['?' for _ in range(len(rows[0]))])
                        merged_conn.executemany(
                            f"INSERT OR REPLACE INTO {table} VALUES ({columns})",
                            rows
                        )
                        merged_conn.commit()
                
                # 提交所有更改
                local_conn.commit()
                github_conn.commit()
                merged_conn.commit()
                
            finally:
                # 关闭所有连接
                if local_conn:
                    local_conn.close()
                if github_conn:
                    github_conn.close()
                if merged_conn:
                    merged_conn.close()
                
                # 等待一下确保连接完全关闭
                time.sleep(1)
                
                # 用合并后的数据库替换本地数据库
                shutil.move(merged_db_path, local_db_path)
                
                # 清理临时文件
                os.unlink(github_db_path)
                if os.path.exists(merged_db_path):
                    os.unlink(merged_db_path)
        
        # 更新 casino.db
        if os.path.exists('casino.db'):
            try:
                # 获取 GitHub 上的数据库内容
                contents = repo.get_contents('casino.db')
                # 合并更新
                merge_db_updates('casino.db', contents.decoded_content, ['casino_records'])
                
                # 更新 GitHub 上的文件
                with open('casino.db', 'rb') as file:
                    content = file.read()
                    repo.update_file(
                        contents.path,
                        f'Update casino.db - {time_str}',
                        content,
                        contents.sha
                    )
            except Exception as e:
                print(f"Casino DB update error: {str(e)}")
        
        # 更新 meter.db
        if os.path.exists('meter.db'):
            try:
                contents = repo.get_contents('meter.db')
                # 合并更新
                merge_db_updates('meter.db', contents.decoded_content, 
                               ['meter_records'])
                
                with open('meter.db', 'rb') as file:
                    content = file.read()
                    repo.update_file(
                        contents.path,
                        f'Update meter.db - {time_str}',
                        content,
                        contents.sha
                    )
            except Exception as e:
                print(f"Meter DB update error: {str(e)}")
        
        return True, "数据库更新成功"
        
    except Exception as e:
        return False, f"更新失败: {str(e)}" 
