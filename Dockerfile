FROM python:3.11-slim
WORKDIR /app
COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt
COPY . .
ENV PYTHONPATH=/app
CMD ["python", "-m", "backend.grpc.master_server"]
