"""Proto package init that exposes generated stubs on sys.path."""

from pathlib import Path
import sys

_generated = Path(__file__).resolve().parent / "generated"
if _generated.exists():
	gen_str = str(_generated)
	if gen_str not in sys.path:
		sys.path.append(gen_str)
