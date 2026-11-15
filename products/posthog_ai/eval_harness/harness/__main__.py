from __future__ import annotations

import os
import sys
import logging
from contextlib import ExitStack
from typing import TYPE_CHECKING

from .cli import HarnessOptions, parse_args
from .django_env import setup_django
from .env_preflight import load_env_file
from .ports import AI_GATEWAY_REDIS_URL, PERSONHOG_ROUTER_PORT
from .providers import SANDBOX_PROVIDER_SETTING, PreflightError
from .terminal import open_terminal
from .transcript import RunTranscript, write_console

if TYPE_CHECKING:
    from .dashboard import EvalDashboard

logger = logging.getLogger("products.posthog_ai.eval_harness")

USAGE_ERROR_EXIT_CODE = 2


def _run(
    options: HarnessOptions, *, transcript: RunTranscript | None = None, dashboard: EvalDashboard | None = None
) -> int:
    # Load the repo-root .env before Django reads the environment, so the harness
    # works without a manual `set -a; source .env`. Shell values win, and the
    # explicit overrides below still trump anything an env file provided.
    load_env_file()

    # Select the sandbox class before Django loads settings. products.tasks resolves
    # settings.SANDBOX_PROVIDER once and caches the class in module globals, so the
    # async-phase override_settings runs too late to change it. .env ships
    # SANDBOX_PROVIDER=docker, so without this a modal run would cache DockerSandbox
    # and execute locally. See SANDBOX_PROVIDER_SETTING. Set unconditionally — on a
    # run without sandboxed suites it only selects a class nothing instantiates.
    os.environ["SANDBOX_PROVIDER"] = SANDBOX_PROVIDER_SETTING[options.provider]

    # Point person/group reads at the harness's own personhog router before Django
    # loads settings. PERSONHOG_ADDR is read from env once at django.setup(), and the
    # personhog client is a cached singleton keyed off that setting at its first call.
    # Bootstrap-phase reads (demo seeding, taxonomy inference) run before the
    # async-phase override_settings, so setting it there would be too late — the
    # singleton is already built. A PERSONHOG_ADDR leaked from a sourced dev .env
    # would otherwise silently point eval reads at the dev persons DB.
    os.environ["PERSONHOG_ADDR"] = f"127.0.0.1:{PERSONHOG_ROUTER_PORT}"

    # HyperCache selects its cache alias at import time. Bootstrap enables
    # gateway projections only after the selected suites start the gateway Redis.
    os.environ["AI_GATEWAY_REDIS_URL"] = AI_GATEWAY_REDIS_URL

    setup_django(keep_logging=transcript is not None)
    if transcript is not None:
        _configure_logging(transcript, verbose=options.verbose)

    # Deferred so Django is configured first: everything below reaches settings,
    # the ORM, or the products.tasks facade at import time.
    from .discovery import SuiteDiscoveryError  # noqa: PLC0415 — must import after django.setup()
    from .lifecycle import SandboxedEvalHarness  # noqa: PLC0415 — must import after django.setup()

    try:
        return SandboxedEvalHarness(options, dashboard=dashboard).run()
    except (PreflightError, SuiteDiscoveryError) as e:
        # A missing prerequisite or a typo'd selector is user error, not a harness
        # bug: say what's wrong without a traceback.
        write_console(f"error: {e}\n", stream=sys.stderr)
        return USAGE_ERROR_EXIT_CODE


def _configure_logging(transcript: RunTranscript | None = None, *, verbose: bool = False) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        force=True,
        handlers=[transcript.logging_handler(verbose=verbose)] if transcript is not None else None,
    )


def use_dashboard(options: HarnessOptions) -> bool:
    if options.interactive is False:
        return False
    # hogli runs evals through a secrets wrapper that pipes stdout, so trust hogli's record of
    # its own stdout. The view draws on /dev/tty, which the pipe does not affect.
    stdout_tty = sys.stdout.isatty() or os.getenv("HOGLI_STDOUT_TTY") == "1"
    terminal = sys.stdin.isatty() and stdout_tty
    if options.interactive is True:
        if not terminal:
            try:
                with open_terminal():
                    pass
            except OSError as error:
                raise PreflightError(
                    f"--tui could not open this session's terminal: {error}. Use --no-tui for a session without a terminal."
                ) from error
        return True
    return terminal and os.getenv("TERM") != "dumb" and not os.getenv("CI")


def _run_captured(options: HarnessOptions, transcript: RunTranscript, dashboard: EvalDashboard | None) -> int:
    _configure_logging(transcript, verbose=options.verbose)
    exit_code = 1
    try:
        try:
            if dashboard is None or dashboard.begin_run():
                if dashboard:
                    logger.info("Interactive eval view ready")
                exit_code = _run(options, transcript=transcript, dashboard=dashboard)
        except KeyboardInterrupt:
            if dashboard is None or dashboard.failure is None:
                logger.warning("Interrupted")
                exit_code = 130
        except Exception:
            logger.exception("Sandboxed eval harness failed")
        finally:
            if dashboard:
                dashboard.end_run()
        if dashboard:
            dashboard.finish(exit_code)
    finally:
        if dashboard and (ui_error := dashboard.failure) is not None:
            logger.error("Interactive eval view failed", exc_info=(type(ui_error), ui_error, ui_error.__traceback__))
            exit_code = 1
        logging.shutdown()
    return exit_code


def main(argv: list[str] | None = None) -> int:
    options = parse_args(argv)
    if options.comparison_models:
        from .comparison import ModelComparison  # noqa: PLC0415 — keep comparison orchestration off normal startup

        transcript = RunTranscript.create()
        try:
            with transcript.capture(verbose=options.verbose):
                _configure_logging(transcript, verbose=options.verbose)
                try:
                    return ModelComparison(options).run()
                except OSError as error:
                    write_console(f"error: Model comparison failed: {error}\n", stream=sys.stderr)
                    return USAGE_ERROR_EXIT_CODE
                finally:
                    logging.shutdown()
        finally:
            transcript.finish()
    if options.list_only:
        _configure_logging()
        return _run(options)

    try:
        interactive = use_dashboard(options)
    except PreflightError as error:
        write_console(f"error: {error}\n", stream=sys.stderr)
        return USAGE_ERROR_EXIT_CODE

    transcript = RunTranscript.create()
    exit_code = 1
    try:
        with ExitStack() as stack:
            dashboard = None
            if interactive:
                from .dashboard import (
                    open_dashboard,  # noqa: PLC0415 — keep the terminal UI off the noninteractive import path
                )

                try:
                    dashboard = stack.enter_context(open_dashboard(transcript.path))
                except (OSError, RuntimeError):
                    with transcript.capture(verbose=options.verbose):
                        _configure_logging(transcript, verbose=options.verbose)
                        logger.exception("Interactive eval view could not start")
                        if options.interactive is not True:
                            write_console("Continuing with plain text output. Use --no-tui to select text output.\n")
                        logging.shutdown()
                    if options.interactive is True:
                        return 1
            with transcript.capture(verbose=options.verbose, console_output=dashboard.write if dashboard else None):
                exit_code = _run_captured(options, transcript, dashboard)
            if dashboard:
                write_console(dashboard.result_text)
    finally:
        transcript.finish()
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
