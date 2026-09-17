from collections.abc import Sequence
from html.parser import HTMLParser
from inspect import getmembers, ismethod

from markdown_it import MarkdownIt
from markdown_it.renderer import RendererProtocol
from markdown_it.token import Token
from markdown_it.utils import EnvType, OptionsDict


# Taken from https://github.com/elespike/mdit_plain/blob/main/src/mdit_plain/renderer.py
class HTMLTextRenderer(HTMLParser):
    def __init__(self):
        super().__init__()
        self._handled_data = []

    def handle_data(self, data):
        self._handled_data.append(data)

    def reset(self):
        self._handled_data = []
        super().reset()

    def render(self, html):
        self.feed(html)
        rendered_data = "".join(self._handled_data)
        self.reset()
        return rendered_data


class RendererPlain(RendererProtocol):
    __output__ = "plain"

    def __init__(self, parser=None):
        self.parser = parser
        self.htmlparser = HTMLTextRenderer()
        self.rules = {
            func_name.replace("render_", ""): func
            for func_name, func in getmembers(self, predicate=ismethod)
            if func_name.startswith("render_")
        }

    def render(self, tokens: Sequence[Token], options: OptionsDict, env: EnvType):
        result = ""
        for i, token in enumerate(tokens):
            rule = self.rules.get(token.type, self.render_default)
            result += rule(tokens, i, options, env)
            if token.children is not None:
                result += self.render(token.children, options, env)
        return result.strip()

    def render_default(self, tokens, i, options, env):
        return ""

    def render_bullet_list_close(self, tokens, i, options, env):
        if (i + 1) == len(tokens) or "list" in tokens[i + 1].type:
            return ""
        return "\n"

    def render_code_block(self, tokens, i, options, env):
        return f"\n{tokens[i].content}\n"

    def render_code_inline(self, tokens, i, options, env):
        return tokens[i].content

    def render_fence(self, tokens, i, options, env):
        return f"\n{tokens[i].content}\n"

    def render_hardbreak(self, tokens, i, options, env):
        return "\n"

    def render_heading_close(self, tokens, i, options, env):
        return "\n"

    def render_heading_open(self, tokens, i, options, env):
        return "\n"

    def render_html_block(self, tokens, i, options, env):
        return self.htmlparser.render(tokens[i].content)

    def render_list_item_open(self, tokens, i, options, env):
        next_token = tokens[i + 1]
        if hasattr(next_token, "hidden") and not next_token.hidden:
            return ""
        return "\n"

    def render_ordered_list_close(self, tokens, i, options, env):
        if (i + 1) == len(tokens) or "list" in tokens[i + 1].type:
            return ""
        return "\n"

    def render_paragraph_close(self, tokens, i, options, env):
        if tokens[i].hidden:
            return ""
        return "\n"

    def render_paragraph_open(self, tokens, i, options, env):
        if tokens[i].hidden:
            return ""
        return "\n"

    def render_softbreak(self, tokens, i, options, env):
        return "\n"

    def render_text(self, tokens, i, options, env):
        return tokens[i].content


def remove_markdown(text: str) -> str:
    parser = MarkdownIt(renderer_cls=RendererPlain)
    return parser.render(text)
