import { useActions } from 'kea'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { LemonField } from 'lib/lemon-ui/LemonField'

import { PropertyDefinition, PropertyDefinitionType, PropertyType } from '~/types'

import { workflowLogic } from '../../../workflowLogic'
import { HogFlowPropertyFilters } from '../../filters/HogFlowFilters'
import { HogFlowAction } from '../../types'
import { ERROR_TRACKING_ISSUE_CREATED_EVENT } from './errorTrackingIssueTrigger'

const ISSUE_PROPERTIES = ['name', 'description', 'severity', 'status', 'assignee', 'first_seen', 'fingerprint']
const PROPERTY_DEFINITIONS: PropertyDefinition[] = ISSUE_PROPERTIES.map((key) => ({
    id: `error-tracking-issue-${key}`,
    name: key,
    type: PropertyDefinitionType.Event,
    property_type: PropertyType.String,
}))

type TriggerAction = Extract<HogFlowAction, { type: 'trigger' }>

export function StepTriggerConfigurationErrorTrackingIssue({ node }: { node: { data: TriggerAction } }): JSX.Element {
    const { setWorkflowActionConfig } = useActions(workflowLogic)
    const config = node.data.config

    return (
        <div className="flex flex-col gap-2 w-full">
            <p className="mb-0 text-sm text-muted-alt">
                This workflow runs when Error tracking creates a new issue, not for every exception. Runs have no
                associated person, so person-dependent steps are unavailable.
            </p>
            <LemonField.Pure label="Issue filters" info="Only run when the new issue matches these properties.">
                <HogFlowPropertyFilters
                    filtersKey={`error-tracking-issue-trigger-${node.data.id}`}
                    filters={{ properties: 'filters' in config ? config.filters?.properties : [] }}
                    setFilters={(filters) =>
                        setWorkflowActionConfig(node.data.id, {
                            type: 'internal-event',
                            filters: {
                                source: 'internal-events',
                                events: [
                                    { id: ERROR_TRACKING_ISSUE_CREATED_EVENT, type: 'events', name: 'Issue created' },
                                ],
                                properties: filters?.properties ?? [],
                            },
                        })
                    }
                    taxonomicGroupTypes={[TaxonomicFilterGroupType.EventProperties]}
                    propertyAllowList={{ [TaxonomicFilterGroupType.EventProperties]: ISSUE_PROPERTIES }}
                    propertyDefinitionsOverride={PROPERTY_DEFINITIONS}
                    taxonomicFilterOptionsFromProp={{
                        [TaxonomicFilterGroupType.EventProperties]: ISSUE_PROPERTIES.map((name) => ({ name })),
                    }}
                    inline
                />
            </LemonField.Pure>
        </div>
    )
}
