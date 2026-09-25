import { pluralize } from 'lib/utils/strings'

import type { FrictionGroupEnumApi, PullRequestFrictionBreakdownApi } from '../generated/api.schemas'
import { compactAgeLabel } from './format'

/** Friction groups in the order the bars stack them: the heaviest group weight first. */
export const FRICTION_GROUP_ORDER: FrictionGroupEnumApi[] = ['queue', 'review', 'ci', 'rework']

export const FRICTION_GROUP_LABELS: Record<FrictionGroupEnumApi, string> = {
    queue: 'Merge queue',
    review: 'Review',
    ci: 'CI',
    rework: 'Rework',
}

export const FRICTION_GROUP_DESCRIPTIONS: Record<FrictionGroupEnumApi, string> = {
    queue: 'time in the merge queue past 30 minutes, and kickouts',
    review: 'the wait for the first approval',
    ci: 'red CI by cause, re-runs that failed again, and CI time past 10 minutes per push',
    rework: 'own failures fixed by a push, extra pushes, and pushes after approval',
}

export const FRICTION_GROUP_COLORS: Record<FrictionGroupEnumApi, string> = {
    queue: 'bg-[var(--data-color-1)]',
    review: 'bg-[var(--data-color-2)]',
    ci: 'bg-[var(--data-color-3)]',
    rework: 'bg-[var(--data-color-4)]',
}

export interface FrictionFact {
    group: FrictionGroupEnumApi
    label: string
    value: string
}

/** What added friction to one pull request, in group order. A zero or unobserved count is left out. */
export function pullRequestFrictionFacts(pr: PullRequestFrictionBreakdownApi): FrictionFact[] {
    const count = (value: number | null | undefined): string | null => (value ? `${value}` : null)
    const duration = (seconds: number | null | undefined): string | null => (seconds ? compactAgeLabel(seconds) : null)
    const ciSeconds = pr.ci_wait_seconds.reduce((sum, seconds) => sum + seconds, 0)
    const facts: [FrictionGroupEnumApi, string, string | null][] = [
        ['queue', 'Time in the merge queue', duration(pr.queue_seconds)],
        ['queue', 'Kicked out of the merge queue', count(pr.kickout_count)],
        ['review', 'Wait for the first approval', duration(pr.first_approval_wait_seconds)],
        ['ci', 'Red, passed on a re-run', count(pr.flake_red_count)],
        ['ci', 'Red, the default branch was failing', count(pr.master_red_count)],
        ['ci', 'Red, cause not provable', count(pr.unknown_red_count)],
        ['ci', 'Re-runs that failed again', count(pr.futile_rerun_count)],
        [
            'ci',
            'CI running',
            ciSeconds ? `${compactAgeLabel(ciSeconds)} over ${pluralize(pr.push_count, 'push', 'pushes')}` : null,
        ],
        ['rework', 'Red until the next push', count(pr.own_red_count)],
        ['rework', 'Extra pushes', count(pr.push_count - 1)],
        ['rework', 'Pushes after approval', count(pr.pushes_after_approval)],
    ]
    return facts.flatMap(([group, label, value]) => (value ? [{ group, label, value }] : []))
}
