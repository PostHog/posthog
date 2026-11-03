import { useValues } from 'kea'

import { IconBolt, IconWarning } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { cohortFilterName } from 'lib/components/PropertyFilters/utils'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { IconOpenInNew } from 'lib/lemon-ui/icons'
import { urls } from 'scenes/urls'

import { cohortsModel } from '~/models/cohortsModel'
import { CohortPropertyFilter } from '~/types'

import { cohortCanBeRestored } from './deletedCohortFilters'

/**
 * The cohort a flag condition targets, linked, with a bolt when flags read its membership in realtime.
 * A deleted or missing cohort renders as a warning instead.
 */
export function CohortConditionLink({ property }: { property: CohortPropertyFilter }): JSX.Element {
    const { cohortsById } = useValues(cohortsModel)
    const realtimeTargetingEnabled = useFeatureFlag('REALTIME_COHORT_FLAG_TARGETING')
    const isRealtime = realtimeTargetingEnabled && cohortsById[property.value]?.realtime?.state === 'ready'

    if (property.cohort_deleted) {
        // A missing cohort has no page to open. A soft-deleted cohort's page has a restore action.
        const restorable = cohortCanBeRestored(property)
        const name = cohortFilterName(property)
        const explanation = restorable
            ? "This cohort was deleted, so the flag can't evaluate this condition. Restore the cohort, choose another cohort, or remove the condition."
            : "This cohort does not exist in this project, so the flag can't evaluate this condition. Choose another cohort or remove the condition."
        return (
            <LemonButton
                type="secondary"
                status="danger"
                size="xsmall"
                to={restorable ? urls.cohort(property.value) : undefined}
                icon={<IconWarning />}
                tooltip={explanation}
                // Without a `to`, LemonButton renders a plain button and uses a string tooltip as its whole
                // accessible name. The label leads with the cohort name so screen readers still announce it.
                aria-label={restorable ? undefined : `${name}. ${explanation}`}
                sideIcon={restorable ? <IconOpenInNew /> : undefined}
            >
                {name}
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
