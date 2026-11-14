FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 BUGFLOW_HOST=0.0.0.0 BUGFLOW_PORT=8080 BUGFLOW_DB=/data/bugflow.sqlite3
WORKDIR /app
COPY index.html styles.css auth.css app.js server.py ./
RUN useradd --create-home --uid 10001 bugflow && mkdir /data && chown bugflow:bugflow /data
USER bugflow
VOLUME ["/data"]
EXPOSE 8080
CMD ["python", "server.py"]
