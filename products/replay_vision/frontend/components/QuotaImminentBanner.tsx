import { LemonBanner } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { pluralize } from 'lib/utils/strings'
import { urls } from 'scenes/urls'

import { ProductKey } from '~/queries/schema/schema-general'

interface Props {
    capReachDate: dayjs.Dayjs
    /** Free-plan orgs have no limit to raise; they need billing instead. */
    onFreePlan: boolean
}

export function QuotaImminentBanner({ capReachDate, onFreePlan }: Props): JSX.Element {
    // Calendar days off the rendered date, so the two can't disagree.
    const days = capReachDate.startOf('day').diff(dayjs().startOf('day'), 'day')
    const timing = days <= 0 ? 'today' : `in ${pluralize(days, 'day')} (${capReachDate.format('MMMM D')})`
    const outcome = onFreePlan ? 'use up your free Vision credits' : 'hit your monthly Vision spend limit'
    return (
        <LemonBanner
            type="warning"
            action={{
                children: onFreePlan ? 'Add billing' : 'Raise your billing limit',
                to: urls.organizationBilling([ProductKey.REPLAY_VISION]),
            }}
        >
            <span className="text-xs">
                Enabled scanners are on track to {outcome} {timing}. Lower the sampling rate to slow spend.
            </span>
        </LemonBanner>
    )
}
