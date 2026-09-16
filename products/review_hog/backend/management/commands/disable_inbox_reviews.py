from products.review_hog.backend.management.inbox_toggle_command import InboxToggleCommand


class Command(InboxToggleCommand):
    help = (
        "Turn off ReviewHog inbox PR reviews (review_inbox_prs) for every active member of the "
        "organization that owns the given team, or for the given user ids."
    )
    field = "review_inbox_prs"
    enabled = False
