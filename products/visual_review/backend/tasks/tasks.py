"""
Celery tasks for visual_review.

Async entrypoints that call the facade (api/api.py).
Keep task functions thin - only call facade methods.
"""
# from celery import shared_task
# from ..api import api
