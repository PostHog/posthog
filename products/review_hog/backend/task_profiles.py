from products.tasks.backend.facade.profiles import TaskProfile

REVIEW = TaskProfile(
    key="review_hog",
    origin_product="review_hog",
    billing_product="review_hog",
    listed=False,
    inherit_user_defaults=False,
    personal_mcp=False,
)

PROFILES = (REVIEW,)
