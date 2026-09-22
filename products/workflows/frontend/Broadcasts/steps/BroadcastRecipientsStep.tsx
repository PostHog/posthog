import { useActions, useValues } from 'kea'

import { IconWarning } from '@posthog/icons'
import { Spinner } from '@posthog/lemon-ui'

import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { humanFriendlyNumber } from 'lib/utils/numbers'
import { COHORTS_ONLY_SUPPORT_IN_PICKER_PROPS } from 'scenes/feature-flags/cohortPickerProps'

import { PropertyFilterType } from '~/types'

import { WORKFLOW_OPERATOR_ALLOWLIST } from '../../Workflows/hogflows/filters/HogFlowFilters'
import { broadcastWizardLogic } from '../broadcastWizardLogic'

function AudienceSizePreview(): JSX.Element | null {
    const { blastRadius, blastRadiusLoading } = useValues(broadcastWizardLogic)

    if (blastRadiusLoading) {
        return <Spinner className="mt-1" />
    }

    if (!blastRadius) {
        return (
            <div className="text-warning text-xs flex items-center gap-1 mt-1">
                <IconWarning className="text-base shrink-0" />
                <span>Couldn't estimate the audience size. Check your filters and try again.</span>
            </div>
        )
    }

    const { affected, total, limit } = blastRadius
    const exceeded = limit != null && affected > limit

    return (
        <div className="text-muted">
            <span className={exceeded ? 'text-danger font-semibold' : undefined}>
                approximately {humanFriendlyNumber(affected)} of {humanFriendlyNumber(total)} people.
            </span>
            {exceeded && (
                <div className="text-danger text-xs">
                    The audience exceeds the limit of {humanFriendlyNumber(limit)} people. Add filters to narrow it
                    down.
                </div>
            )}
        </div>
    )
}

export function BroadcastRecipientsStep(): JSX.Element {
    const { audienceProperties } = useValues(broadcastWizardLogic)
    const { setAudienceProperties } = useActions(broadcastWizardLogic)

    return (
        <div className="flex flex-col gap-2">
            <div>
                <h2 className="m-0 text-xl font-semibold">Who should receive this email?</h2>
                <p className="m-0 text-secondary">
                    Filter by person properties or static cohorts. Without filters, the broadcast goes to everyone.
                </p>
            </div>
            <div>
                <span className="font-semibold">This broadcast will reach</span> <AudienceSizePreview />
            </div>
            <PropertyFilters
                pageKey="broadcast-wizard-recipients"
                propertyFilters={audienceProperties}
                addText="Add condition"
                orFiltering
                sendAllKeyUpdates
                allowRelativeDateOptions
                {...COHORTS_ONLY_SUPPORT_IN_PICKER_PROPS}
                hideBehavioralCohorts
                logicalRowDivider
                onChange={(properties) => setAudienceProperties(properties)}
                taxonomicGroupTypes={[
                    TaxonomicFilterGroupType.PersonProperties,
                    TaxonomicFilterGroupType.Cohorts,
                    TaxonomicFilterGroupType.Metadata,
                ]}
                taxonomicFilterOptionsFromProp={{
                    [TaxonomicFilterGroupType.Metadata]: [
                        { name: 'distinct_id', propertyFilterType: PropertyFilterType.Person },
                    ],
                }}
                hasRowOperator={false}
                operatorAllowlist={WORKFLOW_OPERATOR_ALLOWLIST}
            />
        </div>
    )
}
