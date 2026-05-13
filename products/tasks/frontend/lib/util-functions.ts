import { dayjs } from 'lib/dayjs'
import { humanFriendlyDuration } from 'lib/utils'

export function formatTimeAgo(date: string | Date): string {
    const diff = dayjs().diff(dayjs(date), 'seconds')

    if (diff < 60) {
        return 'just now'
    }

    return `${humanFriendlyDuration(diff, { maxUnits: 1 })} ago`
}

// PostHog Code's desktop client serializes @-mentions as self-closing XML tags like
// `<folder path="products/foo" />`. Newer tasks have these normalized server-side
// before title generation, but already-stored titles can still contain raw tags —
// substitute the bare `path` value (or strip the tag) for display.
const SELF_CLOSING_MENTION_TAG = /<\w+([^>]*?)\s*\/>/g
const MENTION_TAG_PATH_ATTR = /\bpath\s*=\s*"([^"]*)"/

export function stripMentionTags<T extends string | null | undefined>(text: T): T {
    if (text == null) {
        return text
    }
    return text.replace(SELF_CLOSING_MENTION_TAG, (_match, attrs: string) => {
        const pathMatch = attrs.match(MENTION_TAG_PATH_ATTR)
        return pathMatch ? pathMatch[1] : ''
    }) as T
}
