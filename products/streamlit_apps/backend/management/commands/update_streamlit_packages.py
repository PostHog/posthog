import re

from django.core.management.base import BaseCommand, CommandError

from products.streamlit_apps.backend.models import AllowedStreamlitPackage

PACKAGE_NAME_RE = re.compile(r"^[a-zA-Z0-9]([a-zA-Z0-9._-]*[a-zA-Z0-9])?$")


def parse_package_spec(spec: str) -> tuple[str, str]:
    """Parse 'pandas>=2.0,<3.0' into ('pandas', '>=2.0,<3.0')."""
    match = re.match(r"^([a-zA-Z0-9][a-zA-Z0-9._-]*[a-zA-Z0-9]?)(.*)", spec)
    if not match:
        raise CommandError(f"Invalid package spec: {spec}")
    name = match.group(1).lower()
    constraint = match.group(2).strip()
    if not PACKAGE_NAME_RE.match(name):
        raise CommandError(f"Invalid package name: {name}")
    return name, constraint


class Command(BaseCommand):
    help = "Manage the Streamlit apps package allowlist"

    def add_arguments(self, parser):
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument("--add", nargs="+", metavar="PACKAGE", help="Add packages (e.g., 'pandas>=2.0,<3.0')")
        group.add_argument("--remove", nargs="+", metavar="PACKAGE", help="Remove packages by name")
        group.add_argument("--list", action="store_true", help="List all allowed packages")

    def handle(self, *args, **options):
        if options["list"]:
            packages = AllowedStreamlitPackage.objects.order_by("name")
            if not packages.exists():
                self.stdout.write("No packages in allowlist.")
                return
            for pkg in packages:
                self.stdout.write(str(pkg))
            return

        if options["add"]:
            for spec in options["add"]:
                name, constraint = parse_package_spec(spec)
                pkg, created = AllowedStreamlitPackage.objects.update_or_create(
                    name=name,
                    defaults={"version_constraint": constraint},
                )
                action = "Added" if created else "Updated"
                self.stdout.write(f"{action}: {pkg}")
            return

        if options["remove"]:
            for name in options["remove"]:
                name = name.lower()
                deleted, _ = AllowedStreamlitPackage.objects.filter(name=name).delete()
                if deleted:
                    self.stdout.write(f"Removed: {name}")
                else:
                    self.stderr.write(f"Not found: {name}")
