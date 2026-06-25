"""Test quarantine: keep flaky tests from blocking CI, with a hard expiry.

``core`` owns the schema and rules for ``.test_quarantine.json`` (the schema
contract is documented in its module docstring). ``pytest_support`` is the
pytest adapter used by ``posthog/conftest.py``; ``cli`` is the
``hogli test:quarantine`` entrypoint wired via ``hogli.yaml``.
"""
