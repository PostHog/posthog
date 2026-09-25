"""Adapter for the org-scoped managed warehouse provisioning API (duckgres).

Centralizes everything the `DataWarehouseViewSet` provisioning actions need so the
ViewSet stays a thin pass-through: org-scoped feature gating, duckgres org-URL
construction and request/error mapping, warehouse-name validation (shared by provision
and availability checks), and connection presentation.

A managed warehouse is shared by every team in an organization, so the duckgres org
identifier is the PostHog `organization_id` and the Data ops feature flag is evaluated
per organization (not per team).
"""
