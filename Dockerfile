FROM python:3.9-slim

WORKDIR /app

# 安装依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制程序文件
COPY daemon.py .
COPY tg-cli .

# 创建数据目录
RUN mkdir -p /app/data/sessions

# 设置可执行权限
RUN chmod +x tg-cli

# 将 tg-cli 添加到 PATH
RUN ln -s /app/tg-cli /usr/local/bin/tg-cli

# 设置环境变量
ENV TZ=Asia/Shanghai
ENV PYTHONUNBUFFERED=1

# 启动守护进程
CMD ["python3", "-u", "daemon.py"]