from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "users": {
        "description": "A user account at your Teachable school (students, authors, and owners).",
        "docs_url": "https://docs.teachable.com/reference/listusers",
        "columns": {
            "id": "Unique identifier for the user.",
            "name": "The user's full name.",
            "email": "The user's email address.",
        },
    },
    "courses": {
        "description": "A course at your Teachable school.",
        "docs_url": "https://docs.teachable.com/reference/listcourses",
        "columns": {
            "id": "Unique identifier for the course.",
            "name": "The course name.",
            "heading": "The course subtitle, from the Information tab of the course admin.",
            "description": "Text from the Course Description block of the course sales page.",
            "is_published": "Whether the course is published and visible to students.",
            "image_url": "URL of the course image from the Information tab.",
        },
    },
    "course_enrollments": {
        "description": "A student's enrollment in a course, including completion progress.",
        "docs_url": "https://docs.teachable.com/reference/showcourseenrollments",
        "columns": {
            "course_id": "Unique identifier of the course the student is enrolled in.",
            "user_id": "Unique identifier of the enrolled student.",
            "enrolled_at": "When the student enrolled in the course, in ISO8601 format.",
            "expires_at": "When the enrollment expires, or null if it never expires.",
            "completed_at": "When the student completed the course, or null if not yet finished.",
            "percent_complete": "Percentage of the course the student has marked complete.",
        },
    },
    "transactions": {
        "description": "A sales transaction made in your school. Several transactions may belong to a single sale.",
        "docs_url": "https://docs.teachable.com/reference/listtransactions",
        "columns": {
            "id": "Unique identifier for the transaction.",
            "sale_id": "Identifier of the sale this transaction belongs to.",
            "user_id": "Unique identifier of the purchasing user.",
            "pricing_plan_id": "Identifier of the pricing plan the purchase was made under.",
            "created_at": "When the transaction was created, in ISO8601 format.",
            "purchased_at": "The purchase date, which can differ from the creation date for recurring pricing plans.",
            "charge": "Total amount the user paid, calculated in USD by default.",
            "final_price": "The listed price in the currency of choice, excluding fees and taxes.",
            "currency": "Currency of the transaction, in ISO4217 alphabetic code.",
            "tax_charge": "Taxes charged, in the currency of choice.",
            "revenue": "Total amount collected, calculated in USD by default.",
            "status": "Payment status: 'paid', or null when unpaid.",
            "has_chargeback": "Whether a chargeback flagged the transaction as fraudulent.",
            "chargeback_fee": "Fee charged for a chargeback, if any.",
            "affiliate_id": "Identifier of the affiliate credited for the sale, if any.",
            "affiliate_fees": "Fees paid to the affiliate.",
            "author_id": "Identifier of the course author credited for the sale, if any.",
            "author_fees": "Fees paid to the course author.",
            "coupon_id": "Identifier of the coupon applied to the purchase, if any.",
            "refunded_at": "When the transaction was refunded, or null if not refunded.",
            "amount_refunded": "Amount refunded to the user.",
        },
    },
    "pricing_plans": {
        "description": "A pricing plan for a course at your school.",
        "docs_url": "https://docs.teachable.com/reference/listpricingplans",
        "columns": {
            "id": "Unique identifier for the pricing plan.",
            "created_at": "When the pricing plan was created, in ISO8601 format.",
            "updated_at": "When the pricing plan was last updated, in ISO8601 format.",
            "name": "The pricing plan name.",
            "price": "Price as a positive integer in the smallest currency unit (e.g. 100 cents = $1.00 USD).",
            "currency": "Currency of the plan, in ISO4217 alphabetic code.",
            "course_id": "Identifier of the course this pricing plan belongs to.",
        },
    },
}
