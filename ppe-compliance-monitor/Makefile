.PHONY: install migrate run check test docker-build docker-up lint format

install:
	pip install -r requirements.txt

migrate:
	python manage.py migrate

check:
	python manage.py check --deploy

run:
	python manage.py runserver 0.0.0.0:8000

gunicorn:
	gunicorn ppe_project.wsgi:application --bind 0.0.0.0:8000 --workers 3 --timeout 120

check-cameras:
	python manage.py check_cameras

test:
	python manage.py test monitor --verbosity=2

lint:
	python -m flake8 monitor ppe_project || true
	python -m mypy monitor || true

format:
	python -m black monitor ppe_project || true

docker-build:
	docker build -t ppe-kalam:latest .

docker-up:
	docker-compose up --build

collectstatic:
	python manage.py collectstatic --noinput

createsuperuser:
	python manage.py createsuperuser
