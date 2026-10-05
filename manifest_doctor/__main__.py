"""Lets the tool run as `python -m manifest_doctor ...` without installing it."""

from .cli import main

raise SystemExit(main())
