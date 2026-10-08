from products.review_hog.backend.management.toggle_command import SettingsToggleCommand


class Command(SettingsToggleCommand):
    help = (
        "Turn on automatic Flash reviews of authored PRs (default_review_mode 'flash') for every active member of the "
        "organization that owns the given team, or for the given user ids."
    )
    field = "review_authored_prs"
    enabled = True
