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
    ])('renders %s', (_, text, expected) => {
        expect(userMessageDisplayText(text)).toEqual(expected)
    })
})
