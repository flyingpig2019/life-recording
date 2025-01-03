import os
from github import Github
from datetime import datetime
import pytz

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
        current_time = datetime.now(eastern).strftime('%Y-%m-%d %H:%M:%S EST')
        
        # 更新 casino.db
        if os.path.exists('casino.db'):
            with open('casino.db', 'rb') as file:
                content = file.read()
                try:
                    # 尝试获取现有文件
                    contents = repo.get_contents('casino.db')
                    repo.update_file(
                        contents.path,
                        f'Update casino.db - {current_time}',
                        content,
                        contents.sha
                    )
                except:
                    # 如果文件不存在，创建新文件
                    repo.create_file(
                        'casino.db',
                        f'Add casino.db - {current_time}',
                        content
                    )
        
        # 更新 meter.db
        if os.path.exists('meter.db'):
            with open('meter.db', 'rb') as file:
                content = file.read()
                try:
                    contents = repo.get_contents('meter.db')
                    repo.update_file(
                        contents.path,
                        f'Update meter.db - {current_time}',
                        content,
                        contents.sha
                    )
                except:
                    repo.create_file(
                        'meter.db',
                        f'Add meter.db - {current_time}',
                        content
                    )
        
        return True, "数据库更新成功"
    except Exception as e:
        return False, f"更新失败: {str(e)}" 