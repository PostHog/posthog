import { spaceFeedPreview } from './spaceFeedPreview'

describe('spaceFeedPreview', () => {
    it.each([
        ['an empty preview', null, ''],
        ['plain text', 'Fix the flaky test', 'Fix the flaky test'],
        [
            'a leading space context block',
            '<channel_context name="checkout">Repo notes</channel_context>\nFix the flaky test',
            'Fix the flaky test',
        ],
        [
            'PostHog context blocks around the prompt',
            '<posthog_trusted_context>Rules</posthog_trusted_context>Why did signups drop?<posthog_untrusted_context>{}</posthog_untrusted_context>',
            'Why did signups drop?',
        ],
        [
            'a block the preview cut before its closing tag',
            'Retry the webhook\n\n<slack_thread_context>Earlier messages',
            'Retry the webhook',
        ],
        [
            'saved custom instructions',
            '<user_custom_instructions>The user has saved custom instructions that apply to all of their tasks. Follow them.\nUse pnpm</user_custom_instructions>Ship it',
            'Ship it',
        ],
        [
            'a custom-instructions tag the person typed',
            'Explain <user_custom_instructions>how it works</user_custom_instructions>',
            'Explain <user_custom_instructions>how it works</user_custom_instructions>',
        ],
        [
            'self-closing mentions',
            '<github_pr number="42" title="Fix &quot;retry&quot;" url="https://github.com/example/repo/pull/42" /> review <file path="/src/app/main.ts" /> with <skill name="deploy" source="user" path="/skills/deploy" />',
            '@#42 - Fix "retry" review @app/main.ts with /deploy',
        ],
        [
            'paired mentions',
            'Compare <report id="7">Weekly signups</report> to <hogql>SELECT 1</hogql><comment_context label="Line 4">Rename this</comment_context>',
            'Compare Weekly signups to SELECT 1Line 4',
        ],
        ['a mention with nothing to name', 'Look at <insight /> again', 'Look at  again'],
        ['a mention the preview cut mid-tag', 'Check <github_pr number="9" title="Loa', 'Check'],
    ])('cleans %s', (_, text, expected) => {
        expect(spaceFeedPreview(text)).toEqual(expected)
    })
})
