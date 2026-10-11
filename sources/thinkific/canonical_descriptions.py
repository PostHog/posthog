from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Curated from the Thinkific public Admin API docs (https://developers.thinkific.com/api/api-documentation/).
# Partial coverage is fine - any endpoint/column not described here falls back to LLM enrichment.
_DOCS = "https://developers.thinkific.com/api/api-documentation/"

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "courses": {
        "description": "Courses available in your Thinkific school.",
        "docs_url": f"{_DOCS}Courses",
        "columns": {
            "id": "Unique identifier for the course.",
            "name": "Name of the course.",
            "slug": "URL slug used to access the course.",
            "product_id": "Identifier of the product this course belongs to.",
            "instructor_id": "Identifier of the course's primary instructor.",
        },
    },
    "collections": {
        "description": "Course collections (groupings of courses shown on the storefront).",
        "docs_url": f"{_DOCS}Collections",
        "columns": {
            "id": "Unique identifier for the collection.",
            "name": "Name of the collection.",
            "slug": "URL slug for the collection.",
            "course_ids": "Identifiers of the courses contained in this collection.",
        },
    },
    "enrollments": {
        "description": "A user's enrollment in a course, including progress and completion state.",
        "docs_url": f"{_DOCS}Enrollments",
        "columns": {
            "id": "Unique identifier for the enrollment.",
            "user_id": "Identifier of the enrolled user.",
            "user_email": "Email address of the enrolled user.",
            "course_id": "Identifier of the course the user is enrolled in.",
            "course_name": "Name of the course the user is enrolled in.",
            "percentage_completed": "Fraction of the course the user has completed (0.0–1.0).",
            "completed": "Whether the user has completed the course.",
            "is_free_trial": "Whether the enrollment is part of a free trial.",
            "started_at": "Timestamp when the user started the course.",
            "activated_at": "Timestamp when the enrollment became active.",
            "completed_at": "Timestamp when the user completed the course.",
            "expiry_date": "Timestamp when the enrollment expires, if applicable.",
            "created_at": "Timestamp when the enrollment was created.",
            "updated_at": "Timestamp when the enrollment was last updated.",
        },
    },
    "users": {
        "description": "Users (students, instructors, admins) in your Thinkific school.",
        "docs_url": f"{_DOCS}Users",
        "columns": {
            "id": "Unique identifier for the user.",
            "first_name": "User's first name.",
            "last_name": "User's last name.",
            "email": "User's email address.",
            "roles": "Roles assigned to the user (e.g. student, instructor, admin).",
            "created_at": "Timestamp when the user was created.",
        },
    },
    "instructors": {
        "description": "Instructors who can be assigned to courses.",
        "docs_url": f"{_DOCS}Instructors",
        "columns": {
            "id": "Unique identifier for the instructor.",
            "first_name": "Instructor's first name.",
            "last_name": "Instructor's last name.",
            "email": "Instructor's email address.",
            "user_id": "Identifier of the underlying user record.",
        },
    },
    "orders": {
        "description": "Orders placed for products in your Thinkific school.",
        "docs_url": f"{_DOCS}Orders",
        "columns": {
            "id": "Unique identifier for the order.",
            "user_id": "Identifier of the user who placed the order.",
            "user_email": "Email address of the purchasing user.",
            "product_id": "Identifier of the purchased product.",
            "product_name": "Name of the purchased product.",
            "amount_dollars": "Order total in dollars.",
            "status": "Status of the order (e.g. complete, refunded).",
            "created_at": "Timestamp when the order was placed.",
        },
    },
    "products": {
        "description": "Products that can be sold (courses, bundles, memberships).",
        "docs_url": f"{_DOCS}Products",
        "columns": {
            "id": "Unique identifier for the product.",
            "name": "Name of the product.",
            "price": "List price of the product.",
            "productable_type": "Type of object the product wraps (e.g. Course, Bundle).",
        },
    },
    "promotions": {
        "description": "Promotions (discount campaigns) configured in your school.",
        "docs_url": f"{_DOCS}Promotions",
        "columns": {
            "id": "Unique identifier for the promotion.",
            "name": "Name of the promotion.",
            "description": "Description of the promotion.",
        },
    },
    "groups": {
        "description": "Groups used to organize and bulk-enroll users.",
        "docs_url": f"{_DOCS}Groups",
        "columns": {
            "id": "Unique identifier for the group.",
            "name": "Name of the group.",
            "token": "Invite/join token for the group.",
        },
    },
}
