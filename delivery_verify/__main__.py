"""Lets the tool run as `python -m delivery_verify ...` without installing it."""

from .cli import main

raise SystemExit(main())
