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
# Django tags and variables share the attribute with the class list, so remove them before
# splitting. A `{% if %}` branch puts real classes mid-list, and dropping the whole token would
# skip them.
_TEMPLATE_TAG = re.compile(r"\{%.*?%\}|\{\{.*?\}\}")
# Whatever a malformed or multi-line tag leaves behind is not a class name.
_TEMPLATE_SYNTAX = re.compile(r"[{}%|'\"]|^(if|else|endif|elif|for|endfor)$")
# A Tailwind utility as these templates write them: lowercase, digits, dashes, with optional
# variant prefixes such as `hover:` or `sm:`. Deliberately strict, so a stray word in an
# attribute does not become an assertion.
_UTILITY = re.compile(r"^[a-z][a-z0-9]*(-[a-z0-9.]+)*(:[a-z0-9-]+)*$")

# Hooks for the inline script, not utilities, so they are unstyled on purpose. A marker class is
# shaped exactly like a Tailwind utility, so nothing but this list can tell the two apart.
_SCRIPT_HOOKS = frozenset({"toggle-checkbox", "toggle-label"})

# The inline script in preferences.html builds these into `className`, so no `class="..."`
# attribute holds them and the scan cannot reach them. They are listed so the toast and the saving
# state keep their colors if the script moves out of the template or the Tailwind `@source` scope
# stops covering it. A class the script starts to use must be added here by hand.
_SCRIPT_UTILITIES = frozenset(
    {
        "bg-green-500",
        "bg-red-500",
        "duration-500",
        "ease-out",
        "fixed",
        "px-6",
        "py-4",
        "right-4",
        "text-amber-600",
        "text-white",
        "top-4",
        "transform",
    }
)


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
                for token in _TEMPLATE_TAG.sub(" ", attribute).split():
                    if token in _SCRIPT_HOOKS or _TEMPLATE_SYNTAX.search(token) or not _UTILITY.match(token):
                        continue
                    if not _selector_present(css, token):
                        missing.setdefault(template.name, set()).add(token)

        for utility in _SCRIPT_UTILITIES:
            if not _selector_present(css, utility):
                missing.setdefault("preferences.html inline script", set()).add(utility)

        assert not missing, (
            f"These classes are used in the message preference templates but are not in "
            f"{STYLESHEET.name}, so they render unstyled: "
            + "; ".join(f"{name}: {sorted(classes)}" for name, classes in sorted(missing.items()))
            + f". Run `{REBUILD}` and commit the result."
        )
