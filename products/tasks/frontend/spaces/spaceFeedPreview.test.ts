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
    ])('cleans %s', (_, text, expected) => {
        expect(spaceFeedPreview(text)).toEqual(expected)
    })
})
