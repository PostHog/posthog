import sys
import argparse
from pathlib import Path

import modal


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the development egress relay image on Modal")
    parser.add_argument("--app", required=True, help="Development Modal app name")
    parser.add_argument("--env", required=True, help="Modal environment used by the Tasks worker")
    args = parser.parse_args()
    directory = Path(__file__).resolve().parents[1]
    sys.stderr.write(f"Building relay image in Modal environment {args.env} (app {args.app})\n")
    app = modal.App.lookup(args.app, environment_name=args.env, create_if_missing=True)
    image = modal.Image.from_dockerfile(directory / "Dockerfile.relay", context_dir=directory)
    with modal.enable_output():
        image = image.build(app)
    sys.stdout.write(f"{image.object_id}\n")


if __name__ == "__main__":
    main()
