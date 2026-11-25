import { router } from 'kea-router'
import posthog from 'posthog-js'

import { LemonDialog, LemonInput, type LemonMenuItems, lemonToast } from '@posthog/lemon-ui'

import { ApiError } from 'lib/api-error'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { preflightLogic } from 'lib/logic/preflightLogic'
import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'
import { isUUIDLike } from 'lib/utils/guards'
import { urls } from 'scenes/urls'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { getCohortIdentifier } from 'products/data_warehouse/frontend/sql_editor/saveAsTargets'

import {
    getTableForUpdate,
    saveResultCohort,
    saveResultTable,
    type PendingTableUpload,
    type SavedSqlResultTable,
    type SqlResultSource,
} from './sqlResultSnapshot'

function tableUrl(table: SavedSqlResultTable): string {
    return table.sourceId
        ? urls.dataWarehouseSource(`managed-${table.sourceId}`, 'schemas')
        : urls.dataWarehouseSource(`self-managed-${table.id}`, 'configuration')
}

export function savedSqlResultTables(value: unknown): SavedSqlResultTable[] {
    if (!Array.isArray(value)) {
        return []
    }
    return value.filter(
        (table) =>
            table &&
            typeof table.name === 'string' &&
            typeof table.id === 'string' &&
            isUUIDLike(table.id) &&
            (table.sourceId === null || (typeof table.sourceId === 'string' && isUUIDLike(table.sourceId)))
    )
}

function reportSaveError(error: unknown): void {
    const detail = error instanceof ApiError ? (error.data?.message ?? error.detail) : undefined
    lemonToast.error(detail ?? (error instanceof Error ? error.message : 'Could not save the result.'))
}

async function confirmUpdate(
    run: SqlResultSource,
    link: SavedSqlResultTable,
    pending: PendingTableUpload
): Promise<void> {
    let table
    try {
        table = await getTableForUpdate(run.projectId, link)
    } catch (error) {
        reportSaveError(error)
        return
    }
    const createdBy = table.created_by?.email
    posthog.capture('notebook sql result save opened', { target: 'table', operation: 'replace' })
    LemonDialog.open({
        title: `Update ${table.name} from this run?`,
        description: (
            <>
                {createdBy && <p>Table created by {createdBy}.</p>}
                <p>The next sync will replace all rows. People with access to this table can read the saved results.</p>
                <p>Direct SQL queries return up to 300 rows. This sync counts toward warehouse usage.</p>
            </>
        ),
        shouldAwaitSubmit: true,
        secondaryButton: { children: 'Cancel' },
        primaryButton: {
            children: 'Replace rows',
            status: 'danger',
            onClick: async () => {
                try {
                    const updated = await saveResultTable(run, { tableId: table.id }, pending)
                    lemonToast.success(`Started updating ${updated.name}`, {
                        button: { label: 'Manage table', action: () => router.actions.push(tableUrl(updated)) },
                    })
                    posthog.capture('notebook sql result saved', { target: 'table', operation: 'replace' })
                } catch (error) {
                    reportSaveError(error)
                    throw error
                }
            },
        },
    })
}

export function sqlResultMenu({
    source,
    columns,
    defaultName,
    savedTables,
    onTableSaved,
    onRemoveLink,
}: {
    source: SqlResultSource | null
    columns?: string[]
    defaultName: string
    savedTables: SavedSqlResultTable[]
    onTableSaved: (table: SavedSqlResultTable) => void
    onRemoveLink: (id: string) => void
}): LemonMenuItems {
    const warehouseWriteDisabledReason = getAccessControlDisabledReason(
        AccessControlResourceType.WarehouseObjects,
        AccessControlLevel.Editor
    )
    function openDialog(target: 'table' | 'cohort', run: SqlResultSource): void {
        const isTable = target === 'table'
        const pending: PendingTableUpload = {}
        posthog.capture('notebook sql result save opened', { target, operation: 'create' })
        LemonDialog.openForm({
            title: isTable ? 'Save as warehouse table' : 'Save as cohort',
            initialValues: { name: defaultName },
            shouldAwaitSubmit: true,
            primaryButtonProps: { children: 'Save' },
            getPrimaryButtonProps: ({ name }) =>
                isTable && savedTables.some((table) => table.name === name?.trim())
                    ? { children: 'Review update' }
                    : {},
            content: (
                <>
                    <p>
                        {isTable
                            ? 'Create a table from this run. People with access to the table can read its rows. Run the cell and choose Update from this run to replace them.'
                            : 'Create a static cohort from the people in the rows returned by this run.'}{' '}
                        Direct SQL queries return up to 300 rows.
                    </p>
                    <LemonField name="name" label={isTable ? 'Table name' : 'Cohort name'}>
                        <LemonInput autoFocus />
                    </LemonField>
                </>
            ),
            errors: {
                name: (value) => {
                    if (!value?.trim()) {
                        return 'Enter a name.'
                    }
                    if (isTable && !/^[a-zA-Z_][a-zA-Z0-9_]*$/.test(value.trim())) {
                        return 'Use letters, numbers, and underscores. Start with a letter or underscore.'
                    }
                },
            },
            onSubmit: async ({ name }) => {
                try {
                    if (isTable) {
                        const existing = savedTables.find((table) => table.name === name.trim())
                        if (existing) {
                            await confirmUpdate(run, existing, pending)
                            return
                        }
                        const table = await saveResultTable(run, { name: name.trim() }, pending)
                        onTableSaved(table)
                        lemonToast.success(`Saved table ${table.name}`, {
                            button: { label: 'Manage table', action: () => router.actions.push(tableUrl(table)) },
                        })
                    } else {
                        const { cohortCsvMaxBytes } = await import('scenes/cohorts/cohortUtils')
                        const cohort = await saveResultCohort(
                            run,
                            name.trim(),
                            cohortCsvMaxBytes(preflightLogic.values.preflight)
                        )
                        lemonToast.success(`Saved cohort ${cohort.name}`, {
                            button: { label: 'View cohort', action: () => router.actions.push(urls.cohort(cohort.id)) },
                        })
                    }
                    posthog.capture('notebook sql result saved', { target, operation: 'create' })
                } catch (error) {
                    reportSaveError(error)
                    throw error
                }
            },
        })
    }

    return [
        ...(source
            ? [
                  {
                      label: 'Save as warehouse table',
                      disabledReason: warehouseWriteDisabledReason,
                      onClick: () => openDialog('table', source),
                  },
                  {
                      label: 'Save as cohort',
                      disabledReason: getCohortIdentifier(columns)
                          ? undefined
                          : 'Return a person_id, actor_id, or distinct_id column.',
                      onClick: () => openDialog('cohort', source),
                  },
              ]
            : []),
        ...savedTables.map((table) => ({
            title: table.name,
            items: [
                { label: 'Manage table', to: tableUrl(table) },
                source && {
                    label: 'Update from this run',
                    disabledReason: warehouseWriteDisabledReason,
                    onClick: () => confirmUpdate(source, table, {}),
                },
                { label: 'Remove link from cell', onClick: () => onRemoveLink(table.id) },
            ],
        })),
    ]
}
