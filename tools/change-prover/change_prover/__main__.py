"""Entry point for `python -I tools/change-prover/change_prover/__main__.py <command>` from the repository root."""

import os
import sys
from pathlib import Path

# `python -I` keeps the script directory off sys.path, so the package is added by hand.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from change_prover.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:], os.environ))
