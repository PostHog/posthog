"""Django app configuration for the Stampede merge queue."""

from django.apps import AppConfig


class MergeQueueConfig(AppConfig):
    name = "products.merge_queue.backend"
    label = "merge_queue"
