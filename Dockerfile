FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PORT=10000

WORKDIR /app

COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

COPY . /app/

RUN python manage.py collectstatic --no-input
RUN python manage.py migrate && python manage.py seed_data

EXPOSE 10000

CMD ["sh", "-c", "gunicorn chakkimate_core.wsgi:application --bind 0.0.0.0:${PORT:-10000}"]

