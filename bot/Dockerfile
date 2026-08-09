FROM python:3.12-slim

# Не от root: у бота в контейнере лежит база всех пользователей и токен,
# которым можно писать от вашего имени всем клиентам.
RUN useradd --create-home --uid 10001 khilios

WORKDIR /srv

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# База в томе, а не в образе: пересборка не должна уносить подписки.
RUN install -d -o khilios -g khilios /data
VOLUME ["/data"]

USER khilios

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1

CMD ["python", "-m", "app.main"]
