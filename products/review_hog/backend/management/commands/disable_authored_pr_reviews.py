from products.review_hog.backend.management.toggle_command import SettingsToggleCommand


class Command(SettingsToggleCommand):
    help = (
        "Turn off automatic Flash reviews of authored PRs (review_authored_prs) for every active member of the "
        "organization that owns the given team, or for the given user ids. Preserves Flash reasoning effort."
    )
    field = "review_authored_prs"
    enabled = False
