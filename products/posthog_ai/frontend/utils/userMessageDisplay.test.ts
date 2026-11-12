import { fromMarkdown } from 'mdast-util-from-markdown'

import { type MarkdownNode, remarkLiteralHtml } from 'lib/lemon-ui/LemonMarkdown/literalHtml'

import { userMessageDisplayText } from './userMessageDisplay'

function renderedNodes(markdown: string): MarkdownNode[] {
    const tree = fromMarkdown(markdown) as MarkdownNode
    remarkLiteralHtml()(tree)
    const walk = (node: MarkdownNode): MarkdownNode[] => [node, ...(node.children ?? []).flatMap(walk)]
    return walk(tree)
}

describe('userMessageDisplayText', () => {
    it.each([
        ['plain text', 'Fix the flaky test', 'Fix the flaky test'],
        [
            'injected blocks',
            'Ship it\n<user_custom_instructions>The user has saved custom instructions that apply to all of their tasks. Follow them.\nUse pnpm</user_custom_instructions>\n<channel_context channel="web">Notes</channel_context>',
            'Ship it',
        ],
        [
            'a pull request mention',
            '<github_pr number="12" title="Fix [login] &amp; logout" url="https://github.com/example/repo/pull/12" />\nReview this',
            '[#12 - Fix login & logout](https://github.com/example/repo/pull/12)\nReview this',
        ],
        ['an issue mention without a url', 'See <github_issue number="7" />', 'See #7'],
        ['a file mention', 'Read <file path="src/app/main.ts" />', 'Read `app/main.ts`'],
        ['a folder mention', 'Open <folder path="src/app" />', 'Open `app/`'],
        ['a skill mention', 'Run <skill name="deploy" source="user" path="/skills/deploy" /> now', 'Run `/deploy` now'],
        ['two skill mentions', 'Run <skill name="a" /> then <skill name="b" />', 'Run `/a` then `/b`'],
        ['a skill name with a backtick', 'Run <skill name="a`b" />', "Run `/a'b`"],
        ['an unclosed skill opener', 'Run <skill name="deploy" now', 'Run <skill name="deploy" now'],
        ['a skill opener that runs into the next tag', 'Run <skill name="a" <b /> x', 'Run <skill name="a" <b /> x'],
    ])('renders %s', (_, text, expected) => {
        expect(userMessageDisplayText(text)).toEqual(expected)
    })

    it.each([
        ['escaped markup in the name', '<skill name="&lt;img src=x onerror=alert(1)&gt;" />'],
        ['a backtick and markup in the name', '<skill name="x`<img src=x onerror=alert(1)>" />'],
        ['a handler attribute after the name', '<skill name="x" onerror="alert(1)" />'],
        ['a script after the tag', '<skill name="x" /><script>alert(1)</script>'],
    ])('leaves no raw HTML from a skill mention with %s', (_, text) => {
        const nodes = renderedNodes(userMessageDisplayText(text))
        expect(nodes.filter((node) => node.type === 'html')).toEqual([])
    })

    it('keeps markup from an escaped skill name inside inline code', () => {
        const nodes = renderedNodes(userMessageDisplayText('<skill name="&lt;img src=x onerror=alert(1)&gt;" />'))
        expect(nodes.filter((node) => node.type === 'inlineCode').map((node) => node.value)).toEqual([
            '/<img src=x onerror=alert(1)>',
        ])
    })
})
