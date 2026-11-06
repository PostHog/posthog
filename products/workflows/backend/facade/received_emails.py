"""Received email, for products that act on incoming mail and for team deletion."""

from products.workflows.backend.services.inbound_email.retention import RETENTION_DAYS, delete_received_emails_for_teams

__all__ = ["RETENTION_DAYS", "delete_received_emails_for_teams"]
