import sys
import runpy
import argparse
import subprocess
import multiprocessing
from pathlib import Path


def compile_one(source: str, target: str) -> None:
    sys.argv = ["posthog.hogql.cli", "--compile", source, target]
    runpy.run_module("posthog.hogql.cli", run_name="__main__")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("paths", nargs="+")
    args = parser.parse_args()
    if len(args.paths) % 2:
        parser.error("expected source and target pairs")

    # Each compilation gets a fresh process, but shares the cost of importing the compilers.
    multiprocessing.set_forkserver_preload(
        [
            "posthog.hogql.compiler.bytecode",
            "posthog.hogql.compiler.javascript",
            "posthog.settings",
            "posthog.schema",
        ]
    )
    context = multiprocessing.get_context("forkserver")
    checked_targets: set[str] = set()
    for source, target in zip(args.paths[::2], args.paths[1::2], strict=True):
        extension = Path(target).suffix
        if extension not in checked_targets:
            # Keep coverage of the shell entrypoint for both compiler targets.
            subprocess.run(["./bin/hoglang", "compile", source, target], check=True)
            checked_targets.add(extension)
        else:
            process = context.Process(target=compile_one, args=(source, target))
            process.start()
            process.join()
            if process.exitcode != 0:
                raise SystemExit(process.exitcode)


if __name__ == "__main__":
    main()
