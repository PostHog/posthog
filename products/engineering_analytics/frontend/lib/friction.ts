import type { FrictionGroupEnumApi } from '../generated/api.schemas'

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
