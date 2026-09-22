from products.review_hog.backend.management.toggle_command import SettingsToggleCommand


class Command(SettingsToggleCommand):
    help = (
        "Turn off comment resolution after published reviews (resolve_comments) for every active member "
        "of the organization that owns the given team, or for the given user ids."
    )
    field = "resolve_comments"
    enabled = False
