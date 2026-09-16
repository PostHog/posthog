from products.review_hog.backend.management.inbox_toggle_command import InboxToggleCommand


class Command(InboxToggleCommand):
    help = (
        "Turn on Stamphog inbox PR reviews (stamphog_review_inbox_prs) for every active member of the "
        "organization that owns the given team, or for the given user ids."
    )
    field = "stamphog_review_inbox_prs"
    enabled = True
