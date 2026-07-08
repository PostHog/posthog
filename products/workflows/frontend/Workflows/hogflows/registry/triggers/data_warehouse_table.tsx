import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { IconServer } from '@posthog/icons'
import { LemonBanner, LemonSelect } from '@posthog/lemon-ui'

import { DataWarehouseColumnsHint } from 'lib/components/CyclotronJob/DataWarehouseColumnsHint'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { Link } from 'lib/lemon-ui/Link'
import { databaseTableListLogic } from 'scenes/data-management/database/databaseTableListLogic'
import { urls } from 'scenes/urls'

import { HogFlowPropertyFilters } from 'products/workflows/frontend/Workflows/hogflows/filters/HogFlowFilters'
import { registerTriggerType } from 'products/workflows/frontend/Workflows/hogflows/registry/triggers/triggerTypeRegistry'
import { workflowLogic } from 'products/workflows/frontend/Workflows/workflowLogic'

import { HogFlowAction } from '../../types'

export type DataWarehouseTableTriggerConfig = {
    type: 'data-warehouse-table'
    table_name: string
    filters: {
        properties?: any[]
    }
    key_property?: string
}

export function isDataWarehouseTableTriggerConfig(
    config: Extract<HogFlowAction, { type: 'trigger' }>['config']
): config is DataWarehouseTableTriggerConfig {
    return config.type === 'data-warehouse-table'
}

function StepTriggerConfigurationDataWarehouseTable({ node }: { node: any }): JSX.Element {
    const { setWorkflowActionConfig } = useActions(workflowLogic)
    const { actionValidationErrorsById } = useValues(workflowLogic)
    const { externalDataSourceTables, dataWarehouseTables, dataWarehouseTablesMap, databaseLoading } =
        useValues(databaseTableListLogic)
    const { loadDatabase } = useActions(databaseTableListLogic)

    useEffect(() => {
        // The list isn't loaded automatically on mount, so kick it off when the panel opens.
        // Guard on the full table list, not the source-filtered subset, so a project with only
        // self-managed tables (which have no source) doesn't refetch on every mount.
        if (!dataWarehouseTables.length) {
            loadDatabase()
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [])

    const config = node.data.config as DataWarehouseTableTriggerConfig
    const selectedTableName = config.table_name || null
    const properties = config.filters?.properties ?? []
    const validationResult = actionValidationErrorsById[node.data.id]
    const hasNoTables = !databaseLoading && externalDataSourceTables.length === 0

    const tableOptions = externalDataSourceTables.map((table) => ({
        label: table.name,
        value: table.name,
    }))

    const schemaColumns = selectedTableName
        ? Object.values(dataWarehouseTablesMap[selectedTableName]?.fields ?? {})
        : []

    const updateTriggerConfig = (tableName: string | null, newProperties: any[]): void => {
        setWorkflowActionConfig(node.data.id, {
            type: 'data-warehouse-table',
            table_name: tableName ?? '',
            filters: { properties: newProperties },
            // Preserve any existing masking/dedup key set via the API or a future UI
            ...(config.key_property ? { key_property: config.key_property } : {}),
        })
    }

    return (
        <div className="flex flex-col gap-2 w-full">
            <p className="mb-0 text-sm text-muted-alt">
                This workflow runs once for each new row synced into the selected data warehouse table. Runs are
                row-scoped — there is no associated person, so person-dependent steps are unavailable.
            </p>
            <LemonField.Pure label="Data warehouse table" error={validationResult?.errors?.table_name}>
                <LemonSelect
                    options={tableOptions}
                    value={selectedTableName}
                    loading={databaseLoading}
                    disabledReason={hasNoTables ? 'Sync a data warehouse source first' : undefined}
                    onChange={(tableName) => updateTriggerConfig(tableName, properties)}
                    placeholder="Select a table"
                />
                {hasNoTables && (
                    <LemonBanner type="warning" className="w-full mt-1">
                        <p className="mb-0">
                            You don't have any data warehouse tables yet, so this trigger has nothing to listen to. Sync
                            a source first, then come back and pick the table this workflow should run on.{' '}
                            <Link to={urls.dataPipelinesNew('source')} target="_blank" className="font-semibold">
                                Set up a source
                            </Link>
                        </p>
                    </LemonBanner>
                )}
            </LemonField.Pure>

            {selectedTableName ? (
                <DataWarehouseColumnsHint schemaColumns={schemaColumns} tableName={selectedTableName} />
            ) : null}

            <LemonField.Pure label="Only trigger for specific rows">
                <HogFlowPropertyFilters
                    filtersKey={`data-warehouse-table-trigger-${node.data.id}`}
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
    value: 'data-warehouse-table',
    label: 'Data warehouse row synced',
    icon: <IconServer />,
    description: 'Trigger when a new row is synced into a data warehouse table',
    group: 'Data warehouse',
    featureFlag: 'cdp-dwh-table-source',
    matchConfig: (config) => isDataWarehouseTableTriggerConfig(config),
    buildConfig: () => ({
        type: 'data-warehouse-table',
        table_name: '',
        filters: { properties: [] },
    }),
    validate: (config): { valid: boolean; errors: Record<string, string> } | null => {
        if (config.type !== 'data-warehouse-table') {
            return null
        }
        if (!config.table_name) {
            return { valid: false, errors: { table_name: 'Please select a data warehouse table' } }
        }
        return { valid: true, errors: {} }
    },
    ConfigComponent: StepTriggerConfigurationDataWarehouseTable,
})
