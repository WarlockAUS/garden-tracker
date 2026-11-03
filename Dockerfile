FROM python:3.11-slim
WORKDIR /app

ARG APP_VERSION=dev
RUN echo "$APP_VERSION" > /app/version.txt

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN mkdir -p /app/data
EXPOSE 5000
CMD ["python", "app.py"]
