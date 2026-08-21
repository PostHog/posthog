"""Canonical, documentation-sourced descriptions for Cliniko endpoints and columns.

Sourced from the official Cliniko API reference (https://docs.api.cliniko.com/openapi). Keyed by
the resource names in `settings.py` `ENDPOINTS`, which match the `ExternalDataSchema.name` of a
synced Cliniko table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Fields shared by most Cliniko resources; merged into each entry so we don't repeat them.
_COMMON_COLUMNS = {
    "id": "Unique identifier for the record.",
    "created_at": "Time the record was created, in UTC.",
    "updated_at": "Time the record was last updated, in UTC.",
    "archived_at": "Time the record was archived (soft-deleted), or null if still active.",
}


def _columns(**overrides: str) -> dict[str, str]:
    return {**_COMMON_COLUMNS, **overrides}


CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "patients": {
        "description": "A patient (client) record in the practice.",
        "docs_url": "https://docs.api.cliniko.com/openapi/patient",
        "columns": _columns(
            first_name="Patient's first name.",
            last_name="Patient's last name.",
            preferred_first_name="Name the patient prefers to be called.",
            email="Patient's email address.",
            date_of_birth="Patient's date of birth.",
            gender="Patient's gender.",
            sex="Patient's sex.",
            address_1="First line of the patient's address.",
            city="City of the patient's address.",
            state="State or region of the patient's address.",
            post_code="Postal or zip code of the patient's address.",
            country="Country of the patient's address.",
            country_code="ISO 3166-1 country code of the patient's address.",
            time_zone="Patient's time zone.",
            accepted_privacy_policy="Whether the patient has accepted the practice's privacy policy.",
            accepted_email_marketing="Whether the patient has opted in to email marketing.",
            accepted_sms_marketing="Whether the patient has opted in to SMS marketing.",
            deleted_at="Time the record was deleted, or null if not deleted.",
            merged_at="Time this patient record was merged into another, or null if not merged.",
            notes="Free-text notes about the patient.",
        ),
    },
    "individual_appointments": {
        "description": "A one-on-one appointment between a patient and a practitioner.",
        "docs_url": "https://docs.api.cliniko.com/openapi/individual-appointment",
        "columns": _columns(
            starts_at="Time the appointment starts, in UTC.",
            ends_at="Time the appointment ends, in UTC.",
            cancelled_at="Time the appointment was cancelled, or null if not cancelled.",
            cancellation_reason="Reason the appointment was cancelled.",
            cancellation_note="Free-text note about the cancellation.",
            did_not_arrive="Whether the patient failed to arrive for the appointment.",
            patient_arrived="Whether the patient has arrived for the appointment.",
            notes="Free-text notes about the appointment.",
            invoice_status="Billing status of the appointment's invoice.",
            deleted_at="Time the record was deleted, or null if not deleted.",
            telehealth_url="URL for the telehealth video call, if the appointment is a telehealth appointment.",
        ),
    },
    "group_appointments": {
        "description": "An appointment with multiple patient attendees, run by one practitioner.",
        "docs_url": "https://docs.api.cliniko.com/openapi/group-appointment",
        "columns": _columns(
            starts_at="Time the appointment starts, in UTC.",
            ends_at="Time the appointment ends, in UTC.",
            max_attendees="Maximum number of patients that can attend the appointment.",
            notes="Free-text notes about the appointment.",
            deleted_at="Time the record was deleted, or null if not deleted.",
            telehealth_url="URL for the telehealth video call, if the appointment is a telehealth appointment.",
        ),
    },
    "attendees": {
        "description": "A patient's attendance record for one appointment, including arrival and cancellation status.",
        "docs_url": "https://docs.api.cliniko.com/openapi/attendee",
        "columns": _columns(
            arrived="Whether the patient arrived for the appointment.",
            cancelled_at="Time the attendance was cancelled, or null if not cancelled.",
            cancellation_reason="Reason the attendance was cancelled.",
            cancellation_note="Free-text note about the cancellation.",
            invoice_status="Billing status of the attendee's invoice.",
            sent_email_reminders_count="Number of email reminders sent for this appointment.",
            sent_sms_reminders_count="Number of SMS reminders sent for this appointment.",
            treatment_note_status="Status of the treatment note for this attendance (draft or final).",
            deleted_at="Time the record was deleted, or null if not deleted.",
        ),
    },
    "practitioners": {
        "description": "A practitioner (allied health provider) who delivers appointments.",
        "docs_url": "https://docs.api.cliniko.com/openapi/practitioner",
        "columns": _columns(
            first_name="Practitioner's first name.",
            last_name="Practitioner's last name.",
            display_name="Practitioner's display name.",
            label="Practitioner's full label, typically title and name.",
            title="Practitioner's title (e.g. Dr).",
            designation="Practitioner's professional designation.",
            active="Whether the practitioner is currently active.",
            show_in_online_bookings="Whether the practitioner is shown for online bookings.",
            description="Free-text description of the practitioner, shown for online bookings.",
        ),
    },
    "businesses": {
        "description": "A business location (clinic site) within the practice.",
        "docs_url": "https://docs.api.cliniko.com/openapi/business",
        "columns": _columns(
            business_name="Legal or trading name of the business.",
            display_name="Display name of the business.",
            address_1="First line of the business address.",
            city="City of the business address.",
            state="State or region of the business address.",
            post_code="Postal or zip code of the business address.",
            country="Country of the business address.",
            country_code="ISO 3166-1 country code of the business address.",
            time_zone="Human-readable time zone label for the business.",
            time_zone_identifier="IANA time zone identifier for the business.",
            website_address="Business website URL.",
        ),
    },
    "invoices": {
        "description": "A billing invoice raised for a patient's appointment.",
        "docs_url": "https://docs.api.cliniko.com/openapi/invoice",
        "columns": _columns(
            number="Invoice number.",
            issue_date="Date the invoice was issued.",
            status="Billing status of the invoice (open, paid, closed, or open credit).",
            status_description="Human-readable description of the invoice status.",
            total_amount="Total invoice amount, including tax.",
            tax_amount="Total tax amount on the invoice.",
            discounted_amount="Total discount applied to the invoice.",
            net_amount="Net invoice amount, excluding tax.",
            closed_at="Time the invoice was closed, or null if still open.",
            deleted_at="Time the record was deleted, or null if not deleted.",
            notes="Free-text notes about the invoice.",
            online_payment_url="URL where the patient can pay the invoice online.",
        ),
    },
    "invoice_items": {
        "description": "A single line item (service or product) on an invoice.",
        "docs_url": "https://docs.api.cliniko.com/openapi/invoice-item",
        "columns": _columns(
            name="Name of the line item.",
            code="Billing code for the line item.",
            quantity="Quantity of the line item.",
            unit_price="Price per unit before tax and discounts.",
            discount_percentage="Discount percentage applied to the line item.",
            discounted_amount="Discount amount applied to the line item.",
            net_price="Net price of the line item, excluding tax.",
            tax_name="Name of the tax applied to the line item.",
            tax_rate="Tax rate applied to the line item.",
            tax_amount="Tax amount applied to the line item.",
            total_including_tax="Total price of the line item, including tax.",
            is_monetary_discount="Whether the discount is a fixed amount rather than a percentage.",
            deleted_at="Time the record was deleted, or null if not deleted.",
        ),
    },
    "treatment_notes": {
        "description": "A clinical treatment note recorded for a patient's appointment.",
        "docs_url": "https://docs.api.cliniko.com/openapi/treatment-note",
        "columns": _columns(
            title="Title of the treatment note.",
            content="Content of the treatment note.",
            author_name="Name of the person who authored the treatment note.",
            draft="Whether the treatment note is still a draft.",
            finalized_at="Time the treatment note was finalized, or null if still a draft.",
            pinned_at="Time the treatment note was pinned to the patient's record, or null if not pinned.",
            deleted_at="Time the record was deleted, or null if not deleted.",
        ),
    },
    "appointment_types": {
        "description": "A configurable type of appointment (e.g. Initial Consultation), with duration and pricing defaults.",
        "docs_url": "https://docs.api.cliniko.com/openapi/appointment-type",
        "columns": _columns(
            name="Name of the appointment type.",
            description="Description of the appointment type, shown for online bookings.",
            category="Category the appointment type belongs to.",
            color="Colour used to represent the appointment type in the calendar.",
            duration_in_minutes="Default duration of the appointment type, in minutes.",
            max_attendees="Maximum number of attendees allowed for the appointment type.",
            show_in_online_bookings="Whether the appointment type is available for online bookings.",
            telehealth_enabled="Whether the appointment type supports telehealth.",
            online_payments_enabled="Whether online payment is enabled for the appointment type.",
            deposit_price="Deposit price required to book the appointment type online.",
        ),
    },
    "referral_sources": {
        "description": "How a patient was referred to the practice (e.g. a referring doctor or marketing channel).",
        "docs_url": "https://docs.api.cliniko.com/openapi/referral-source",
        "columns": _columns(
            referrer="Name of the referrer.",
            referrer_type="Type of the referrer.",
            subcategory="Subcategory of the referral source.",
            notes="Free-text notes about the referral source.",
        ),
    },
    "products": {
        "description": "A stock item (e.g. retail product) that can be sold or used in appointments.",
        "docs_url": "https://docs.api.cliniko.com/openapi/product",
        "columns": _columns(
            name="Name of the product.",
            item_code="Item code for the product.",
            serial_number="Serial number of the product.",
            cost_price="Cost price of the product.",
            price_ex_tax="Sale price of the product, excluding tax.",
            price_including_tax="Sale price of the product, including tax.",
            stock_level="Current stock level of the product.",
            notes="Free-text notes about the product.",
        ),
    },
}
