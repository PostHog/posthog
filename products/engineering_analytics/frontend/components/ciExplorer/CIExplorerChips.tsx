import { LemonTag, LemonTagType } from '@posthog/lemon-ui'

import { pluralize } from 'lib/utils/strings'

import type { JobLogBadgeApi } from '../../generated/api.schemas'

function counted(text: string, count: number): string {
    return count > 1 ? `${text} ×${count}` : text
}

function chip(badge: JobLogBadgeApi): { text: string; type: LemonTagType } {
    if (badge.kind === 'migrations') {
        return {
            text: badge.state === 'applied' ? pluralize(badge.count, 'migration') : 'no migrations',
            type: 'muted',
        }
    }
    switch (badge.state) {
        case 'hit':
            return { text: counted('cache hit', badge.count), type: 'success' }
        case 'partial':
            return { text: counted('older cache', badge.count), type: 'warning' }
        case 'failed':
            return { text: counted('cache restore failed', badge.count), type: 'warning' }
        default:
            return { text: counted('cache miss', badge.count), type: 'warning' }
    }
}

/** What a job's log says a step did, a few words each. The cache keys are in the chip's tooltip. */
export function CIExplorerChips({ badges }: { badges: JobLogBadgeApi[] }): JSX.Element {
    return (
        <>
            {badges.map((badge) => {
                const { text, type } = chip(badge)
                return (
                    <LemonTag
                        key={`${badge.kind}-${badge.state}`}
                        type={type}
                        size="small"
                        title={badge.detail.filter(Boolean).join('\n')}
                    >
                        {text}
                    </LemonTag>
                )
            })}
        </>
    )
}
