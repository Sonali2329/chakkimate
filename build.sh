#!/usr/bin/env bash
# Exit on error
set -o errexit

echo "--- Installing dependencies ---"
pip install -r requirements.txt

echo "--- Collecting static files ---"
python manage.py collectstatic --no-input

echo "--- Running database migrations ---"
python manage.py migrate

echo "--- Seeding default master data ---"
python manage.py seed_data

echo "--- Build completed successfully! ---"
