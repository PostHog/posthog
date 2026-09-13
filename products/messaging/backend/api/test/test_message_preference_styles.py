import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

TEMPLATE_DIR = Path(settings.BASE_DIR) / "posthog" / "templates" / "message_preferences"
STYLESHEET = Path(settings.BASE_DIR) / "frontend" / "public" / "message-preferences.css"
REBUILD = "pnpm --filter=@posthog/frontend build:message-preferences"

# Tailwind compiles these templates ahead of time, so a class added to the markup does nothing
# until someone reruns the build. Nothing else notices: the page still renders, just unstyled.
_CLASS_ATTRIBUTE = re.compile(r'class="([^"]*)"')
# Django tags and variables share the attribute with the class list, and `{% if %}` branches put
# them mid-list, so drop anything carrying template syntax rather than trying to evaluate it.
_TEMPLATE_SYNTAX = re.compile(r"[{}%|'\"]|^(if|else|endif|elif|for|endfor)$")
# A Tailwind utility as these templates write them: lowercase, digits, dashes, with optional
# variant prefixes such as `hover:` or `sm:`. Deliberately strict, so a stray word in an
# attribute does not become an assertion.
_UTILITY = re.compile(r"^[a-z][a-z0-9]*(-[a-z0-9.]+)*(:[a-z0-9-]+)*$")

# Hooks for the inline script, not utilities, so they are unstyled on purpose. A marker class is
# shaped exactly like a Tailwind utility, so nothing but this list can tell the two apart.
_SCRIPT_HOOKS = frozenset({"toggle-checkbox", "toggle-label"})


def _selector_present(css: str, utility: str) -> bool:
    # Tailwind escapes the characters that are not selector-safe, so `hover:shadow-md` is written
    # `.hover\:shadow-md`. The trailing guard stops `.flex` matching inside `.flex-1`.
    escaped = re.escape(utility).replace(":", r"\\:")
    return re.search(r"\." + escaped + r"(?![a-zA-Z0-9_-])", css) is not None


class TestMessagePreferenceStyles(SimpleTestCase):
    def test_every_class_in_the_templates_is_in_the_compiled_stylesheet(self) -> None:
        css = STYLESHEET.read_text()

        missing: dict[str, set[str]] = {}
        for template in sorted(TEMPLATE_DIR.glob("*.html")):
            for attribute in _CLASS_ATTRIBUTE.findall(template.read_text()):
                for token in attribute.split():
                    if token in _SCRIPT_HOOKS or _TEMPLATE_SYNTAX.search(token) or not _UTILITY.match(token):
                        continue
                    if not _selector_present(css, token):
                        missing.setdefault(template.name, set()).add(token)

        assert not missing, (
            f"These classes are used in the message preference templates but are not in "
            f"{STYLESHEET.name}, so they render unstyled: "
            + "; ".join(f"{name}: {sorted(classes)}" for name, classes in sorted(missing.items()))
            + f". Run `{REBUILD}` and commit the result."
        )
