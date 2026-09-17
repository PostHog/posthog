import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { IconServer } from '@posthog/icons'
import { LemonBanner, LemonSelect, LemonTag } from '@posthog/lemon-ui'

import { DataWarehouseColumnsHint } from 'lib/components/CyclotronJob/DataWarehouseColumnsHint'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { Link } from 'lib/lemon-ui/Link'
import { databaseTableListLogic } from 'scenes/data-management/database/databaseTableListLogic'
import { dataWarehouseViewsLogic } from 'scenes/data-warehouse/saved_queries/dataWarehouseViewsLogic'
import { urls } from 'scenes/urls'

import { HogFlowPropertyFilters } from 'products/workflows/frontend/Workflows/hogflows/filters/HogFlowFilters'
import { registerTriggerType } from 'products/workflows/frontend/Workflows/hogflows/registry/triggers/triggerTypeRegistry'
import { workflowLogic } from 'products/workflows/frontend/Workflows/workflowLogic'

import { HogFlowAction } from '../../types'

export type DataWarehouseViewTriggerConfig = {
    type: 'data-warehouse-view'
    table_name: string
    filters: {
        properties?: any[]
    }
    key_property?: string
}

export function isDataWarehouseViewTriggerConfig(
    config: Extract<HogFlowAction, { type: 'trigger' }>['config']
): config is DataWarehouseViewTriggerConfig {
    return config.type === 'data-warehouse-view'
}

function StepTriggerConfigurationDataWarehouseView({ node }: { node: any }): JSX.Element {
    const { setWorkflowActionConfig } = useActions(workflowLogic)
    const { actionValidationErrorsById } = useValues(workflowLogic)
    const { dataWarehouseTables, dataWarehouseTablesMap, views, databaseLoading } = useValues(databaseTableListLogic)
    const { loadDatabase, ensureAllTableFields } = useActions(databaseTableListLogic)
    const { dataWarehouseSavedQueryMapById, dataWarehouseSavedQueriesLoading } = useValues(dataWarehouseViewsLogic)

    useEffect(() => {
        // The list isn't loaded automatically on mount, so kick it off when the panel opens.
        if (!dataWarehouseTables.length && !views.length) {
            loadDatabase()
        } else {
            // The store may hold a shallow (fields-less) schema left by the SQL editor.
            ensureAllTableFields()
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [])

    const config = node.data.config as DataWarehouseViewTriggerConfig
    const selectedTableName = config.table_name || null
    const properties = config.filters?.properties ?? []
    const validationResult = actionValidationErrorsById[node.data.id]

    // Only a materialized view writes rows on a schedule, so a plain view has nothing to trigger on.
    const materializedViews = views.filter((view) => dataWarehouseSavedQueryMapById[view.id]?.is_materialized)
    // The list needs both logics: the names come from the database schema and the materialized flag
    // from the saved queries. Waiting on only one of them claims the project has no views while the
    // other is still in flight.
    const loading = databaseLoading || dataWarehouseSavedQueriesLoading
    const hasNoViews = !loading && materializedViews.length === 0

    const viewOptions = materializedViews.map((view) => {
        const incremental = dataWarehouseSavedQueryMapById[view.id]?.is_incremental
        return {
            label: view.name,
            value: view.name,
            labelInMenu: (
                <span className="flex items-center gap-2">
                    {view.name}
                    <LemonTag type={incremental ? 'success' : 'warning'}>
                        {incremental ? 'Incremental' : 'Full refresh'}
                    </LemonTag>
                </span>
            ),
        }
    })

    const selectedView = materializedViews.find((view) => view.name === selectedTableName)
    const selectedSavedQuery = selectedView ? dataWarehouseSavedQueryMapById[selectedView.id] : undefined
    const selectedIsFullRefresh = !!selectedView && !selectedSavedQuery?.is_incremental

    const schemaColumns = selectedTableName
        ? Object.values(dataWarehouseTablesMap[selectedTableName]?.fields ?? {})
        : []

    const updateTriggerConfig = (tableName: string | null, newProperties: any[]): void => {
        setWorkflowActionConfig(node.data.id, {
            type: 'data-warehouse-view',
            table_name: tableName ?? '',
            filters: { properties: newProperties },
            // Preserve any existing masking/dedup key set via the API or a future UI
            ...(config.key_property ? { key_property: config.key_property } : {}),
        })
    }

    return (
        <div className="flex flex-col gap-2 w-full">
            <p className="mb-0 text-sm text-muted-alt">
                This workflow runs once for each row a materialized view adds or updates. Runs are row-scoped, so there
                is no associated person and person-dependent steps are unavailable.
            </p>
            <LemonField.Pure label="Materialized view" error={validationResult?.errors?.table_name}>
                <LemonSelect
                    options={viewOptions}
                    value={selectedTableName}
                    loading={loading}
                    disabledReason={hasNoViews ? 'Materialize a view first' : undefined}
                    onChange={(tableName) => updateTriggerConfig(tableName, properties)}
                    placeholder="Select a materialized view"
                />
                {hasNoViews && (
                    <LemonBanner type="warning" className="w-full mt-1">
                        <p className="mb-0">
                            You don't have any materialized views yet, so this trigger has nothing to listen to.
                            Materialize a view first, then come back and pick the one this workflow should run on.{' '}
                            <Link to={urls.sqlEditor({})} target="_blank" className="font-semibold">
                                Open the SQL editor
                            </Link>
                        </p>
                    </LemonBanner>
                )}
            </LemonField.Pure>

            {selectedIsFullRefresh && (
                <LemonBanner type="warning" className="w-full">
                    <p className="mb-0">
                        This view rebuilds its whole table on every run, so every row runs this workflow again each
                        time. Set the view to update incrementally to run only on the rows that changed.{' '}
                        {selectedView && (
                            <Link
                                to={urls.sqlEditor({ view_id: selectedView.id })}
                                target="_blank"
                                className="font-semibold"
                            >
                                Open the view
                            </Link>
                        )}
                    </p>
                </LemonBanner>
            )}

            {selectedTableName ? (
                <DataWarehouseColumnsHint schemaColumns={schemaColumns} tableName={selectedTableName} />
            ) : null}

            <LemonField.Pure label="Only trigger for specific rows">
                <HogFlowPropertyFilters
                    filtersKey={`data-warehouse-view-trigger-${node.data.id}`}
                    filters={{ properties }}
                    setFilters={(filters) => updateTriggerConfig(selectedTableName, filters?.properties ?? [])}
                    schemaColumns={schemaColumns}
                    dataWarehouseTableName={selectedTableName ?? undefined}
                />
            </LemonField.Pure>
        </div>
    )
}

registerTriggerType({
    value: 'data-warehouse-view',
    label: 'Materialized view row updated',
    icon: <IconServer />,
    description: 'Trigger when a materialized view adds or updates a row',
    group: 'Data warehouse',
    featureFlag: 'cdp-dwh-view-source',
    matchConfig: (config) => isDataWarehouseViewTriggerConfig(config),
    buildConfig: () => ({
        type: 'data-warehouse-view',
        table_name: '',
        filters: { properties: [] },
    }),
    validate: (config): { valid: boolean; errors: Record<string, string> } | null => {
        if (config.type !== 'data-warehouse-view') {
            return null
        }
        if (!config.table_name) {
            return { valid: false, errors: { table_name: 'Please select a materialized view' } }
        }
        return { valid: true, errors: {} }
    },
    ConfigComponent: StepTriggerConfigurationDataWarehouseView,
})
