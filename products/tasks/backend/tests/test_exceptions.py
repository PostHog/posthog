from products.tasks.backend.exceptions import SandboxNotRunningError


def test_temporal_failure_type_defaults_to_class_name():
    error = SandboxNotRunningError("boom", {}, cause=RuntimeError("x"), capture=False)
    assert error.type == "SandboxNotRunningError"
    assert not error.non_retryable
