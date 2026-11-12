import { marked } from 'marked'

import { userMessageDisplayText } from './userMessageDisplay'

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
        ['a skill name with escaped markup', 'Run <skill name="&lt;b&gt;" />', 'Run `/<b>`'],
        ['a skill opener that runs into the next tag', 'Run <skill name="a" <b /> x', 'Run <skill name="a" <b /> x'],
    ])('renders %s', (_, text, expected) => {
        expect(userMessageDisplayText(text)).toEqual(expected)
    })

    it('keeps markup from an escaped skill name inside a code element', () => {
        // `marked` keeps raw HTML, so markup that escaped the code span would show up as a live element.
        const html = marked.parse(userMessageDisplayText('<skill name="&lt;img src=x onerror=alert(1)&gt;" />'), {
            async: false,
        })
        expect(html).toContain('<code>/&lt;img src=x onerror=alert(1)&gt;</code>')
        expect(html).not.toContain('<img')
    })
})
