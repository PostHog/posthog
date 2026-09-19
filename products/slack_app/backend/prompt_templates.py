from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined


class PromptTemplates:
    """The Jinja prompt templates in ``root``, rendered by name.

    A prompt is prose the whole team reads and edits, and the eval suites are the only
    real test of it. Holding it in ``<name>.md.j2`` next to the code that sends it means
    a wording change shows up as a diff of the wording rather than of Python quoting.

    The ``.md.j2`` suffix keeps the repo's markdown formatters off the files. `--fix`
    dedents a bullet list and puts a blank line in front of it, which changes what the
    model reads.
    """

    def __init__(self, root: Path) -> None:
        self._environment = Environment(
            loader=FileSystemLoader(root),
            # The default renders a missing name as the empty string, which drops a
            # paragraph of the prompt rather than failing.
            undefined=StrictUndefined,
            # nosemgrep: python.jinja2.security.audit.autoescape-disabled-false.incorrect-autoescape-disabled -- the output is a prompt, not HTML. Escaping would send an apostrophe in a Slack message to the model as &#39;.
            autoescape=False,
            trim_blocks=True,
            lstrip_blocks=True,
        )

    def render(self, name: str, /, **values: object) -> str:
        """The prompt in ``<name>.md.j2``, rendered with ``values``."""
        return self._environment.get_template(f"{name}.md.j2").render(values)
