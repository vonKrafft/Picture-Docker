FROM python:3-alpine

COPY requirements.txt ./

RUN apk update \
    && apk add --no-cache gcc libressl-dev musl-dev libffi-dev jpeg-dev zlib-dev \
    && pip install --no-cache-dir -r requirements.txt \
    && apk del gcc \
    && addgroup -S -g 1000 app \
    && adduser -S -u 1000 -G app app

EXPOSE 8080
