from products.review_hog.backend.management.toggle_command import SettingsToggleCommand


class Command(SettingsToggleCommand):
    help = (
        "Turn on ReviewHog inbox PR reviews (review_inbox_prs) for every active member of the "
        "organization that owns the given team, or for the given user ids."
    )
    field = "review_inbox_prs"
    enabled = True
