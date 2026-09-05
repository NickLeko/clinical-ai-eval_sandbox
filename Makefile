.PHONY: test compile verify acceptance reviewer-package reviewer-report

acceptance:
	python -m src.acceptance

test:
	python -m unittest discover -s tests -v

compile:
	python -m py_compile src/*.py tests/*.py

verify: test compile

reviewer-package:
	python src/build_reviewer_report.py --results-dir results

reviewer-report: reviewer-package
