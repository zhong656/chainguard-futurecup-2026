# 与 CI / 本地开发保持同一个 Python 版本（3.11），避免线上与本地行为不一致
FROM python:3.11-slim

WORKDIR /app

# 先装依赖再拷代码：代码变动不会让依赖层缓存失效
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PYTHONUNBUFFERED=1
# 容器里没有 .git，commit_sha 由环境变量提供（_commit_sha() 优先读它）
ENV GIT_COMMIT=0000000
EXPOSE 8000

# 健康检查：容器能自己判断服务是否就绪
HEALTHCHECK --interval=15s --timeout=5s --start-period=25s --retries=3 \
    CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/docs', timeout=3)"

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
