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

// The mentions the composer writes into a prompt. A card shows each one as the label PostHog Desktop prints for it.
const ID_MENTION_TAGS = ['error', 'experiment', 'insight', 'feature_flag']
const OBJECT_MENTION_TAGS = [
    'dashboard',
    'replay',
    'flag',
    'survey',
    'ticket',
    'report',
    'trace',
    'eval',
    'event',
    'cohort',
    'action',
    'person',
]
const SELF_CLOSING_MENTION_TAGS = [
    'file',
    'folder',
    'skill',
    ...ID_MENTION_TAGS,
    ...OBJECT_MENTION_TAGS,
    'github_issue',
    'github_pr',
]
const PAIRED_MENTION_TAGS = ['report', 'hogql', 'comment_context']

const COMPLETE_BLOCK = new RegExp(`<(${INJECTED_TAGS.join('|')})\\b[^>]*>[\\s\\S]*?</\\1>`, 'g')
const CUSTOM_INSTRUCTIONS_BLOCK = new RegExp(
    `<${CUSTOM_INSTRUCTIONS_TAG}\\b[^>]*>([\\s\\S]*?)</${CUSTOM_INSTRUCTIONS_TAG}>`,
    'g'
)
// The API truncates previews, which can cut a block before its closing tag.
const TRUNCATED_BLOCK = new RegExp(
    `<(${[...INJECTED_TAGS, CUSTOM_INSTRUCTIONS_TAG].join('|')})\\b(?![\\s\\S]*</\\1>)[\\s\\S]*$`
)
const MENTION_TAG = new RegExp(
    `<(${SELF_CLOSING_MENTION_TAGS.join('|')})\\b([^>]*?)\\s*/>|<(${PAIRED_MENTION_TAGS.join('|')})\\b([^>]*)>([\\s\\S]*?)</\\3>`,
    'g'
)
// Runs after the complete mentions are gone, so any mention tag left is one the truncation cut.
const TRUNCATED_MENTION = new RegExp(
    `<(?:${SELF_CLOSING_MENTION_TAGS.join('|')})\\b[^>]*$|<(${PAIRED_MENTION_TAGS.join('|')})\\b(?![\\s\\S]*</\\1>)[\\s\\S]*$`
)
const XML_ATTR = /(\w+)="([^"]*)"/g

function unescapeXml(value: string): string {
    return value
        .replace(/&quot;/g, '"')
        .replace(/&apos;/g, "'")
        .replace(/&lt;/g, '<')
        .replace(/&gt;/g, '>')
        .replace(/&amp;/g, '&')
}

function parseAttrs(raw: string): Record<string, string> {
    const attrs: Record<string, string> = {}
    for (const [, name, value] of raw.matchAll(XML_ATTR)) {
        attrs[name] = unescapeXml(value)
    }
    return attrs
}

/** A file mention shows its folder and name, like `spaces/SpaceFeed.tsx`. */
function fileLabel(path: string): string {
    const segments = path.split('/').filter(Boolean)
    const name = segments.pop() ?? path
    const folder = segments.pop()
    return folder ? `${folder}/${name}` : name
}

/** The text Desktop prints for a mention, or an empty string for a tag with nothing to name. */
function mentionLabel(tag: string, attrs: Record<string, string>, body: string): string {
    if (tag === 'file' || tag === 'folder') {
        return attrs.path ? `@${fileLabel(attrs.path)}` : ''
    }
    if (tag === 'skill') {
        return attrs.name ? `/${attrs.name}` : ''
    }
    if (ID_MENTION_TAGS.includes(tag)) {
        return attrs.id ? `@${attrs.id}` : ''
    }
    if (tag === 'github_issue' || tag === 'github_pr') {
        if (!attrs.number && !attrs.url) {
            return ''
        }
        return attrs.title ? `@#${attrs.number ?? ''} - ${attrs.title}` : `@#${attrs.number ?? ''}`
    }
    if (tag === 'hogql') {
        return unescapeXml(body).trim()
    }
    if (tag === 'comment_context') {
        return attrs.label || 'Comment'
    }
    // A PostHog object. A paired report carries its name as the tag body.
    return attrs.id ? unescapeXml(body).trim() || attrs.id : ''
}

export function stripInjectedBlocks(text: string): string {
    return text
        .replace(COMPLETE_BLOCK, '')
        .replace(CUSTOM_INSTRUCTIONS_BLOCK, (block: string, inner: string) =>
            inner.trimStart().startsWith(CUSTOM_INSTRUCTIONS_PREAMBLE) ? '' : block
        )
        .replace(/\n{3,}/g, '\n\n')
        .trim()
}

export function spaceFeedPreview(text: string | null | undefined): string {
    if (!text) {
        return ''
    }
    return stripInjectedBlocks(text)
        .replace(TRUNCATED_BLOCK, '')
        .replace(
            MENTION_TAG,
            (
                _: string,
                selfClosingTag: string | undefined,
                selfClosingAttrs: string | undefined,
                pairedTag: string | undefined,
                pairedAttrs: string | undefined,
                body: string | undefined
            ) =>
                mentionLabel(
                    selfClosingTag ?? pairedTag ?? '',
                    parseAttrs(selfClosingAttrs ?? pairedAttrs ?? ''),
                    body ?? ''
                )
        )
        .replace(TRUNCATED_MENTION, '')
        .replace(/\n{3,}/g, '\n\n')
        .trim()
}
