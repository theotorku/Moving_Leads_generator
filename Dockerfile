FROM python:3.11-alpine

WORKDIR /app

COPY ./requirements.txt /app

RUN apk add --no-cache gcc musl-dev libffi-dev python3-dev \
    && pip install --no-cache-dir -r requirements.txt

COPY . /app

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
