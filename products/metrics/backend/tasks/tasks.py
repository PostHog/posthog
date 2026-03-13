"""
Celery tasks for metrics.

Async entrypoints that call the facade (facade/api.py).
Keep task functions thin - only call facade methods.
"""
# from celery import shared_task
# from ..facade import api
