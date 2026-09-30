// Blocks the agent tooling injects into a session prompt. They are instructions for the agent, not text the
// person wrote, so a feed card must not show them. Mirrors the tag list PostHog Desktop strips.
const INJECTED_TAGS = [
    'channel_context',
    'canvas_generation_instructions',
    'posthog_trusted_context',
    'posthog_untrusted_context',
    'posthog_context',
    'onboarding_brief',
    'slack_thread_context',
]
const CUSTOM_INSTRUCTIONS_TAG = 'user_custom_instructions'
const CUSTOM_INSTRUCTIONS_PREAMBLE = 'The user has saved custom instructions that apply to all of their tasks.'

const COMPLETE_BLOCK = new RegExp(`<(${INJECTED_TAGS.join('|')})\\b[^>]*>[\\s\\S]*?</\\1>`, 'g')
const CUSTOM_INSTRUCTIONS_BLOCK = new RegExp(
    `<${CUSTOM_INSTRUCTIONS_TAG}\\b[^>]*>([\\s\\S]*?)</${CUSTOM_INSTRUCTIONS_TAG}>`,
    'g'
)
// The API truncates previews, which can cut a block before its closing tag.
const TRUNCATED_BLOCK = new RegExp(
    `<(${[...INJECTED_TAGS, CUSTOM_INSTRUCTIONS_TAG].join('|')})\\b(?![\\s\\S]*</\\1>)[\\s\\S]*$`
)

export function spaceFeedPreview(text: string | null | undefined): string {
    if (!text) {
        return ''
    }
    return text
        .replace(COMPLETE_BLOCK, '')
        .replace(CUSTOM_INSTRUCTIONS_BLOCK, (block: string, inner: string) =>
            inner.trimStart().startsWith(CUSTOM_INSTRUCTIONS_PREAMBLE) ? '' : block
        )
        .replace(TRUNCATED_BLOCK, '')
        .replace(/\n{3,}/g, '\n\n')
        .trim()
}
