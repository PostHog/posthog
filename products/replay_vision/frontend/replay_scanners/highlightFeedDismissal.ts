import type { LemonMenuItems } from 'lib/lemon-ui/LemonMenu/LemonMenu'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import posthog from 'lib/posthog-typed'

import { visionObservationsFeedDismissalCreate, visionObservationsFeedDismissalDestroy } from '../generated/api'
import type { FeedDismissalReasonEnumApi, HighlightFeedItemApi } from '../generated/api.schemas'

export const FEED_DISMISSAL_REASON_LABELS: Record<FeedDismissalReasonEnumApi, string> = {
    not_a_real_problem: 'Not a real problem',
    already_known: 'Already known',
    not_my_area: 'Not my area',
    other: 'Other reason',
}

export function feedDismissalMenuItems(onDismiss: (reason: FeedDismissalReasonEnumApi | null) => void): LemonMenuItems {
    const reasons = Object.entries(FEED_DISMISSAL_REASON_LABELS) as [FeedDismissalReasonEnumApi, string][]
    return [
        {
            title: 'Why is this not useful?',
            items: reasons.map(([reason, label]) => ({
                label,
                onClick: () => onDismiss(reason),
                'data-attr': `vision-highlight-feed-dismiss-${reason}`,
            })),
        },
        {
            items: [
                {
                    label: 'Hide without a reason',
                    onClick: () => onDismiss(null),
                    'data-attr': 'vision-highlight-feed-dismiss-no-reason',
                },
            ],
        },
    ]
}

export function withoutFeedItem(
    items: HighlightFeedItemApi[] | null,
    observationId: string
): HighlightFeedItemApi[] | null {
    return items?.filter((item) => item.observation.id !== observationId) ?? null
}

/** Puts an item back where it was, or at the end when the list has since shrunk below that place. */
export function withFeedItemRestored(
    items: HighlightFeedItemApi[] | null,
    item: HighlightFeedItemApi,
    position: number
): HighlightFeedItemApi[] | null {
    if (!items || items.some((existing) => existing.observation.id === item.observation.id)) {
        return items
    }
    const next = [...items]
    next.splice(Math.min(position, next.length), 0, item)
    return next
}

interface DismissFeedItemArgs {
    teamId: number
    item: HighlightFeedItemApi
    reason: FeedDismissalReasonEnumApi | null
    properties: Record<string, unknown>
    restore: () => void
}

export async function dismissFeedItem({
    teamId,
    item,
    reason,
    properties,
    restore,
}: DismissFeedItemArgs): Promise<void> {
    const observationId = item.observation.id
    try {
        await visionObservationsFeedDismissalCreate(String(teamId), observationId, { reason })
    } catch {
        restore()
        lemonToast.error("Couldn't hide this session. Try again.")
        return
    }
    posthog.capture('replay_vision_highlight_clip_dismissed', { ...properties, dismissal_reason: reason })
    const undo = async (): Promise<void> => {
        try {
            await visionObservationsFeedDismissalDestroy(String(teamId), observationId)
        } catch {
            lemonToast.error("Couldn't bring this session back.", {
                toastId: `vision-highlight-feed-undo-failed-${observationId}`,
                button: { label: 'Try again', dataAttr: 'vision-highlight-feed-dismiss-undo-retry', action: undo },
            })
            return
        }
        posthog.capture('replay_vision_highlight_clip_dismiss_undone', properties)
        restore()
    }
    // Keyed per observation, so a second dismissal gets its own toast instead of merging into the first.
    lemonToast.success('Hidden from your feed', {
        toastId: `vision-highlight-feed-dismissed-${observationId}`,
        button: { label: 'Undo', dataAttr: 'vision-highlight-feed-dismiss-undo', action: undo },
    })
}
