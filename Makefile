.PHONY: install run test demo
install:
	pip install -r requirements-dev.txt
run:
	uvicorn app.main:app --reload
test:
	pytest -q
demo:
	python scripts/demo.py --n 200
