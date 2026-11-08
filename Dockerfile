FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn
COPY . .
CMD ["gunicorn", "config.wsgi", "-b", "0.0.0.0:8000", "--workers", "3", "--timeout", "120"]
