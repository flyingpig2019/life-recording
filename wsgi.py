from waitress import serve
from app import app
import os

if __name__ == '__main__':
    # 获取端口号，如果环境变量中没有设置，则默认使用 8080
    port = int(os.environ.get('PORT', 8080))
    
    # 启动 waitress 服务器
    print(f'Starting waitress server on port {port}...')
    serve(app, host='0.0.0.0', port=port) 