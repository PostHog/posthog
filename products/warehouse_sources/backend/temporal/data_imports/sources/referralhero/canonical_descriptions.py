from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.referralhero.settings import API_DOCS_URL

OBJECTS_URL = "https://support.referralhero.com/integrate/rest-api/objects"

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "lists": {
        "description": "Active ReferralHero campaigns that contain subscribers.",
        "docs_url": OBJECTS_URL,
        "columns": {
            "uuid": "Unique identifier of the campaign.",
            "name": "Campaign name.",
            "subscribers": "Number of subscribers in the campaign.",
            "created_at": "Unix timestamp when the campaign was created.",
        },
    },
    "subscribers": {
        "description": "People registered in an active campaign, with referral and conversion details.",
        "docs_url": OBJECTS_URL,
        "columns": {
            "list_uuid": "Identifier of the campaign that contains this subscriber.",
            "id": "Unique identifier of the subscriber.",
            "email": "Subscriber email address.",
            "code": "Referral code for the subscriber.",
            "referred_by": "Information about the subscriber who referred this person.",
            "people_referred": "Number of referrals from the subscriber.",
            "created_at": "Time when the subscriber joined the campaign.",
        },
    },
    "bonuses": {
        "description": "Reward definitions configured for an active campaign.",
        "docs_url": OBJECTS_URL,
        "columns": {
            "list_uuid": "Identifier of the campaign that offers this reward.",
            "title": "Reward name.",
            "description": "Reward description.",
            "referrals": "Number of referrals required to earn the reward.",
        },
    },
    "rewards": {
        "description": "Rewards earned by subscribers in active campaigns.",
        "docs_url": API_DOCS_URL,
        "columns": {
            "list_uuid": "Identifier of the campaign that issued the reward.",
            "subscriber_id": "Identifier of the subscriber who earned the reward.",
            "status": "Reward status, such as pending, sent, resent, canceled, or flagged.",
            "transaction_id": "Identifier of the transaction associated with the reward.",
        },
    },
    "coupon_groups": {
        "description": "Coupon groups and their coupons in active campaigns.",
        "docs_url": API_DOCS_URL,
        "columns": {
            "list_uuid": "Identifier of the campaign that contains this coupon group.",
            "id": "Coupon group identifier.",
            "name": "Coupon group name.",
            "active": "Whether the coupon group is active.",
            "coupons": "Coupons in the group, including availability and delivery details.",
        },
    },
}
