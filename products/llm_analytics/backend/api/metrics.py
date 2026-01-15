"""
Prometheus metrics for LLM Analytics API endpoints.

This module provides latency histograms and helper decorators for tracking
API endpoint performance. These metrics complement the basic request/error
counters provided by the @monitor decorator.

Usage:
    from products.llm_analytics.backend.api.metrics import llma_track_latency

    @llma_track_latency("llma_proxy_completion")
    @monitor(feature=None, endpoint="llma_proxy_completion", method="POST")
    def completion(self, request, *args, **kwargs):
        ...
"""

import time
from collections.abc import Callable
from functools import wraps
from typing import TypeVar

from prometheus_client import Counter, Histogram

# Type variable for preserving function signatures
F = TypeVar("F", bound=Callable)


# Latency histogram for API request duration
# Buckets are tuned for typical API response times (100ms to 60s)
LLMA_REQUEST_LATENCY = Histogram(
    "llma_request_duration_seconds",
    "LLM Analytics API request latency in seconds",
    labelnames=["endpoint"],
    buckets=[0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0],
)


# Latency histogram specifically for LLM provider calls (longer timeouts expected)
# Buckets are tuned for LLM API calls which can take 30-120+ seconds
LLMA_LLM_CALL_LATENCY = Histogram(
    "llma_llm_call_duration_seconds",
    "Time spent waiting for LLM provider API calls",
    labelnames=["endpoint", "provider"],
    buckets=[0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0],
)


# Error counter for LLM-specific errors (provider failures, timeouts, etc.)
LLMA_LLM_ERRORS = Counter(
    "llma_errors_total",
    "LLM provider errors by endpoint and error type",
    labelnames=["endpoint", "error_type"],
)


def llma_track_latency(endpoint: str) -> Callable[[F], F]:
    """
    Decorator to track endpoint latency using Prometheus histograms.

    This decorator measures the total time taken by an endpoint and records
    it in the LLMA_REQUEST_LATENCY histogram. Use this in addition to @monitor
    for endpoints where latency tracking is important.

    Args:
        endpoint: The endpoint name label for the metric (should match @monitor endpoint)

    Example:
        @llma_track_latency("llma_proxy_completion")
        @monitor(feature=None, endpoint="llma_proxy_completion", method="POST")
        def completion(self, request, *args, **kwargs):
            ...
    """

    def decorator(func: F) -> F:
        @wraps(func)
        def wrapper(*args, **kwargs):
            start = time.perf_counter()
            try:
                return func(*args, **kwargs)
            finally:
                duration = time.perf_counter() - start
                LLMA_REQUEST_LATENCY.labels(endpoint=endpoint).observe(duration)

        return wrapper  # type: ignore[return-value]

    return decorator


def llma_track_llm_call_latency(endpoint: str, provider: str) -> Callable[[F], F]:
    """
    Decorator to track LLM provider call latency.

    Use this for functions that make calls to external LLM providers
    (OpenAI, Anthropic, etc.) to track provider-specific latency.

    Args:
        endpoint: The endpoint name label
        provider: The LLM provider name (e.g., "openai", "anthropic")

    Example:
        @llma_track_llm_call_latency("llma_summarize", "openai")
        def call_openai_for_summary(text):
            ...
    """

    def decorator(func: F) -> F:
        @wraps(func)
        def wrapper(*args, **kwargs):
            start = time.perf_counter()
            try:
                return func(*args, **kwargs)
            finally:
                duration = time.perf_counter() - start
                LLMA_LLM_CALL_LATENCY.labels(endpoint=endpoint, provider=provider).observe(duration)

        return wrapper  # type: ignore[return-value]

    return decorator


def llma_record_error(endpoint: str, error_type: str) -> None:
    """
    Record an LLM-specific error.

    Call this when an LLM provider returns an error or times out.

    Args:
        endpoint: The endpoint name label
        error_type: The type of error (e.g., "timeout", "rate_limit", "api_error")

    Example:
        try:
            response = openai_client.chat.completions.create(...)
        except openai.RateLimitError:
            llma_record_error("llma_summarize", "rate_limit")
            raise
    """
    LLMA_LLM_ERRORS.labels(endpoint=endpoint, error_type=error_type).inc()
