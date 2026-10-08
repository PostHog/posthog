"""Kept separate from ``facade/api.py`` because ``CustomerAnalyticsConfig.ready`` imports it
during ``django.setup()``, so it must stay import-light."""

from products.workflows.backend.services.account_audience import register_account_audience_provider

__all__ = ["register_account_audience_provider"]
