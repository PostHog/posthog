"""Multi-processing worker initialization.

Keep this module without any imports to avoid conflicts when bootstrapping
multiprocessing workers."""


def init_worker() -> None:
    import django  # noqa: PLC0415 - this module must stay free of imports at load time

    django.setup()
