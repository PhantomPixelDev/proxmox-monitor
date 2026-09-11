.PHONY: screenshots screenshots-mock screenshots-diff screenshots-guard

# Capture screenshots with mock data (no PVE needed) — produces 7 PNGs in docs/screenshots
screenshots:
	python scripts/capture_screenshots.py --mock

screenshots-mock:
	python scripts/capture_screenshots.py --mock

# Guard: re-capture and diff against committed PNGs; fails CI if drift detected, uploads artifact for review
screenshots-diff: screenshots-mock
	git diff --exit-code -- docs/screenshots || (echo "::warning::screenshots drift detected — run 'make screenshots' and commit"; git diff --stat -- docs/screenshots; exit 1)

screenshots-guard: screenshots-diff
