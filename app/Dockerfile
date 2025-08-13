FROM python:slim

ENV PYTHONUNBUFFERED 1 \
    DJANGO_SUPERUSER_PASSWORD admin \
    DJANGO_SUPERUSER_USERNAME admin \
    PYTHONDONTWRITEBYTECODE 1

RUN apt-get update && apt-get install -y \
    gcc \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir app
WORKDIR /app

COPY ./requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
