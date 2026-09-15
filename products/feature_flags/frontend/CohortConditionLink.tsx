import { useValues } from 'kea'

import { IconBolt } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { IconOpenInNew } from 'lib/lemon-ui/icons'
import { urls } from 'scenes/urls'

import { cohortsModel } from '~/models/cohortsModel'
import { CohortPropertyFilter } from '~/types'

/** The cohort a flag condition targets, linked, with a bolt when flags read its membership in realtime. */
export function CohortConditionLink({ property }: { property: CohortPropertyFilter }): JSX.Element {
    const { cohortsById } = useValues(cohortsModel)
    const isRealtime = cohortsById[property.value]?.realtime?.state === 'ready'

    return (
        <LemonButton
            type="secondary"
            size="xsmall"
            to={urls.cohort(property.value)}
            icon={isRealtime ? <IconBolt /> : undefined}
            tooltip={
                isRealtime ? 'Realtime cohort. Feature flags see membership changes within about a minute.' : undefined
            }
            sideIcon={<IconOpenInNew />}
        >
            {property.cohort_name || `ID ${property.value}`}
        </LemonButton>
    )
}
