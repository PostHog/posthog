import { capitalizeFirstLetter } from 'lib/utils/strings'

import { Noun } from '~/models/groupsModel'
import { LifecycleToggle } from '~/types'

export const lifecycles: { name: LifecycleToggle; color: string }[] = [
    {
        name: 'new',
        color: 'var(--color-lifecycle-new)',
    },
    {
        name: 'returning',
        color: 'var(--color-lifecycle-returning)',
    },
    {
        name: 'resurrecting',
        color: 'var(--color-lifecycle-resurrecting)',
    },
    {
        name: 'dormant',
        color: 'var(--color-lifecycle-dormant)',
    },
]

export const DEFAULT_LIFECYCLE_TOGGLES: LifecycleToggle[] = ['new', 'returning', 'resurrecting', 'dormant']

export function getLifecycleTooltip(
    lifecycle: LifecycleToggle,
    aggregationTargetLabel: Noun,
    aggregationTargetPronoun: 'that' | 'who'
): string {
    switch (lifecycle) {
        case 'new':
            return `${capitalizeFirstLetter(
                aggregationTargetLabel.plural
            )} ${aggregationTargetPronoun} did the event or action during the interval and were also created during that period, e.g. created an account and sent a message today.`
        case 'returning':
            return `${capitalizeFirstLetter(
                aggregationTargetLabel.singular
            )} ${aggregationTargetPronoun} was active in the previous interval and is also active in the current interval, e.g. sent a message yesterday and also sent a message today.`
        case 'resurrecting':
            return `${capitalizeFirstLetter(
                aggregationTargetLabel.singular
            )} ${aggregationTargetPronoun} was not active in the previous interval but became active once again, e.g. did not send any messages for 10 days, but sent one today.`
        case 'dormant':
            return `${capitalizeFirstLetter(
                aggregationTargetLabel.plural
            )} ${aggregationTargetPronoun} are not active in the current interval, but were active in the previous interval, e.g. did not send a message today, but sent one yesterday.`
    }
}
