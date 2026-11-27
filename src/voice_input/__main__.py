"""Allow ``python -m voice_input``."""

from __future__ import annotations

import sys

from voice_input.cli import main

sys.exit(main())
