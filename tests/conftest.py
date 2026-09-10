import os

# Qt needs a platform plugin; CI has no display
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
