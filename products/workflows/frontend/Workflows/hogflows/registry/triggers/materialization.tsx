import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { IconServer } from '@posthog/icons'
import { LemonBanner, LemonSelect } from '@posthog/lemon-ui'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { Link } from 'lib/lemon-ui/Link'
import { dataWarehouseViewsLogic } from 'scenes/data-warehouse/saved_queries/dataWarehouseViewsLogic'
import { urls } from 'scenes/urls'

import { PropertyDefinition, PropertyDefinitionType, PropertyType } from '~/types'

import { HogFlowPropertyFilters } from 'products/workflows/frontend/Workflows/hogflows/filters/HogFlowFilters'
import { registerTriggerType } from 'products/workflows/frontend/Workflows/hogflows/registry/triggers/triggerTypeRegistry'
import { workflowLogic } from 'products/workflows/frontend/Workflows/workflowLogic'

import {
    MATERIALIZATION_JOB_FINISHED_EVENT,
    MATERIALIZATION_OUTCOME_OPTIONS,
    MaterializationOutcome,
    decodeMaterializationFilters,
    encodeMaterializationFilters,
    isMaterializationJobTriggerConfig,
} from './materializationTriggerFilters'
import { InternalEventTriggerConfig } from './slackTriggerFilters'

const ADVANCED_PROPERTIES: { key: string; type: PropertyType }[] = [
    { key: 'rows_materialized', type: PropertyType.Numeric },
    { key: 'duration_seconds', type: PropertyType.Numeric },
    { key: 'error', type: PropertyType.String },
]

const ADVANCED_PROPERTY_DEFINITIONS: PropertyDefinition[] = ADVANCED_PROPERTIES.map(({ key, type }) => ({
    id: `materialization-job-${key}`,
    name: key,
    type: PropertyDefinitionType.Event,
    property_type: type,
}))

function StepTriggerConfigurationMaterializationJob({ node }: { node: any }): JSX.Element {
    const { setWorkflowActionConfig } = useActions(workflowLogic)
    const { dataWarehouseSavedQueries, dataWarehouseSavedQueriesLoading } = useValues(dataWarehouseViewsLogic)
    const { loadDataWarehouseSavedQueries } = useActions(dataWarehouseViewsLogic)

    useEffect(() => {
        if (!dataWarehouseSavedQueries.length) {
            loadDataWarehouseSavedQueries()
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [])

    const config = node.data.config as InternalEventTriggerConfig
    const filters = decodeMaterializationFilters(config.filters?.properties)

    const materializedViews = dataWarehouseSavedQueries.filter((view) => view.is_materialized)
    const hasNoViews = !dataWarehouseSavedQueriesLoading && materializedViews.length === 0

    const update = (changes: Partial<typeof filters>): void => {
        setWorkflowActionConfig(node.data.id, {
            type: 'internal-event',
            filters: {
                source: 'internal-events',
                events: [{ id: MATERIALIZATION_JOB_FINISHED_EVENT, type: 'events' }],
                properties: encodeMaterializationFilters({ ...filters, ...changes }),
            },
        })
    }

    return (
        <div className="flex flex-col gap-2 w-full">
            <p className="mb-0 text-sm text-muted-alt">
                This workflow runs once each time a materialized view finishes refreshing. Runs have no associated
                person, so person-dependent steps are unavailable.
            </p>

            <LemonField.Pure label="Materialized view" info="Leave empty to run for every materialized view.">
                <LemonSelect
                    options={[
                        { label: 'Any materialized view', value: null },
                        ...materializedViews.map((view) => ({ label: view.name, value: view.name })),
                    ]}
                    value={filters.viewName}
                    loading={dataWarehouseSavedQueriesLoading}
                    onChange={(viewName) => update({ viewName })}
                    data-attr="materialization-trigger-view"
                />
                {hasNoViews && (
                    <LemonBanner type="warning" className="w-full mt-1">
                        <p className="mb-0">
                            You don't have any materialized views yet, so this trigger has nothing to listen to.
                            Materialize a view first, then come back and pick it.{' '}
                            <Link to={urls.sqlEditor({})} target="_blank" className="font-semibold">
                                Open the SQL editor
                            </Link>
                        </p>
                    </LemonBanner>
                )}
            </LemonField.Pure>

            <LemonField.Pure label="Outcome">
                <LemonSelect<MaterializationOutcome>
                    value={filters.outcome}
                    options={MATERIALIZATION_OUTCOME_OPTIONS.map(({ value, label, description }) => ({
                        value,
                        label,
                        labelInMenu: (
                            <div className="flex flex-col py-1">
                                <span>{label}</span>
                                <span className="text-xs text-muted-alt">{description}</span>
                            </div>
                        ),
                    }))}
                    onChange={(outcome) => update({ outcome })}
                    data-attr="materialization-trigger-outcome"
                />
            </LemonField.Pure>

            <LemonField.Pure
                label="Additional filters"
                info="Match on the row count, how long the run took, or the error text."
            >
                <HogFlowPropertyFilters
                    filtersKey={`materialization-trigger-${node.data.id}`}
                    filters={{ properties: filters.additional }}
                    setFilters={(next) => update({ additional: next?.properties ?? [] })}
                    taxonomicGroupTypes={[TaxonomicFilterGroupType.EventProperties]}
                    propertyAllowList={{
                        [TaxonomicFilterGroupType.EventProperties]: ADVANCED_PROPERTIES.map((p) => p.key),
                    }}
                    propertyDefinitionsOverride={ADVANCED_PROPERTY_DEFINITIONS}
                    taxonomicFilterOptionsFromProp={{
                        [TaxonomicFilterGroupType.EventProperties]: ADVANCED_PROPERTIES.map((p) => ({ name: p.key })),
                    }}
                    inline
                />
            </LemonField.Pure>
        </div>
    )
}

registerTriggerType({
    value: 'materialization-job',
    label: 'Materialized view refreshed',
    icon: <IconServer />,
    description: 'Trigger when a materialized view finishes refreshing, with or without an error',
    group: 'Data warehouse',
    featureFlag: 'materialization-workflow-triggers',
    matchConfig: (config) => isMaterializationJobTriggerConfig(config),
    buildConfig: () => ({
        type: 'internal-event',
        filters: {
            source: 'internal-events',
            events: [{ id: MATERIALIZATION_JOB_FINISHED_EVENT, type: 'events' }],
            properties: encodeMaterializationFilters({ viewName: null, outcome: 'failed', additional: [] }),
        },
    }),
    ConfigComponent: StepTriggerConfigurationMaterializationJob,
})
