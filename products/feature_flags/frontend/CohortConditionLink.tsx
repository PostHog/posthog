import { useValues } from 'kea'

import { IconBolt, IconWarning } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { cohortFilterName } from 'lib/components/PropertyFilters/utils'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { IconOpenInNew } from 'lib/lemon-ui/icons'
import { urls } from 'scenes/urls'

import { cohortsModel } from '~/models/cohortsModel'
import { CohortPropertyFilter } from '~/types'

/**
 * The cohort a flag condition targets, linked, with a bolt when flags read its membership in realtime.
 * A deleted or missing cohort renders as a warning instead.
 */
export function CohortConditionLink({ property }: { property: CohortPropertyFilter }): JSX.Element {
    const { cohortsById } = useValues(cohortsModel)
    const realtimeTargetingEnabled = useFeatureFlag('REALTIME_COHORT_FLAG_TARGETING')
    const isRealtime = realtimeTargetingEnabled && cohortsById[property.value]?.realtime?.state === 'ready'

    if (property.cohort_deleted) {
        // A cohort with no name is missing and has no page to open. A soft-deleted cohort's page
        // has a restore action.
        const restorable = !!property.cohort_name
        return (
            <LemonButton
                type="secondary"
                status="danger"
                size="xsmall"
                to={restorable ? urls.cohort(property.value) : undefined}
                icon={<IconWarning />}
                tooltip={`This cohort was deleted, so the flag can't evaluate this condition. ${
                    restorable
                        ? 'Restore the cohort, choose another cohort, or remove the condition.'
                        : 'Choose another cohort or remove the condition.'
                }`}
                sideIcon={restorable ? <IconOpenInNew /> : undefined}
            >
                {cohortFilterName(property)}
            </LemonButton>
        )
    }

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
            {cohortFilterName(property)}
        </LemonButton>
    )
}
