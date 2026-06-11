"""
Object storage helpers for legal documents — kept separate from logic/ so
admin.py (autodiscovered very early by django.contrib.admin) doesn't transitively
pull ee.billing.BillingManager and trigger an import cycle.
"""

from __future__ import annotations

from django.conf import settings

from .models import LegalDocument


def signed_pdf_storage_key(document: LegalDocument) -> str:
    """
    Canonical key under which the signed PDF lives in object storage. The
    document uuid is the natural identifier and never changes, so admins
    regenerating the envelope for the same row just overwrite the old object.
    """
    return f"{settings.OBJECT_STORAGE_LEGAL_DOCUMENTS_FOLDER}/{document.id}.pdf"
