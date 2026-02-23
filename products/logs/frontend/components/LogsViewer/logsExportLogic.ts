import { actions, connect, kea, key, listeners, path, props } from 'kea'
import Papa from 'papaparse'
import posthog from 'posthog-js'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { copyToClipboard } from 'lib/utils/copyToClipboard'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { PropertyGroupFilter, SidePanelTab } from '~/types'

import { logsViewerConfigLogic } from 'products/logs/frontend/components/LogsViewer/config/logsViewerConfigLogic'

import { ParsedLogMessage } from '../../types'
import { logsViewerFiltersLogic } from './Filters/logsViewerFiltersLogic'
import { logsViewerDataLogic } from './data/logsViewerDataLogic'
import type { logsExportLogicType } from './logsExportLogicType'
import { logsViewerLogic } from './logsViewerLogic'

function triggerBlobDownload(blob: Blob, filename: string): void {
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = filename
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    setTimeout(() => URL.revokeObjectURL(url), 0)
}

function exportTimestamp(): string {
    return new Date().toISOString().slice(0, 19).replace(/:/g, '-')
}

export function getExportColumns(attributeColumns: string[]): string[] {
    const base = ['timestamp', 'severity_text', ...attributeColumns, 'body']
    // Only include raw attribute JSON if no specific columns are configured
    if (attributeColumns.length === 0) {
        base.push('attributes', 'resource_attributes')
    }
    return base
}

export interface LogsExportLogicProps {
    id: string
}

export const logsExportLogic = kea<logsExportLogicType>([
    path((id) => ['products', 'logs', 'frontend', 'components', 'LogsViewer', 'logsExportLogic', id]),
    props({} as LogsExportLogicProps),
    key((props) => props.id),
    connect(({ id }: LogsExportLogicProps) => ({
        values: [
            logsViewerLogic({ id }),
            ['selectedLogsArray', 'attributeColumns'],
            logsViewerFiltersLogic({ id }),
            ['filters', 'utcDateRange'],
            logsViewerDataLogic({ id }),
            ['maxExportableLogs'],
            logsViewerConfigLogic({ id }),
            ['orderBy'],
        ],
        actions: [sidePanelStateLogic, ['openSidePanel']],
    })),

    actions({
        copySelectedLogs: true,
        exportSelectedAsCsv: true,
        exportServerSide: (totalLogsCount?: number) => ({ totalLogsCount }),
    }),

    listeners(({ actions, values }) => ({
        copySelectedLogs: () => {
            const selectedLogs = values.selectedLogsArray
            posthog.capture('logs bulk copy', { count: selectedLogs.length })
            const text = selectedLogs.map((log: ParsedLogMessage) => log.body).join('\n')
            void copyToClipboard(text, `${selectedLogs.length} log message${selectedLogs.length === 1 ? '' : 's'}`)
        },
        exportSelectedAsCsv: () => {
            const selectedLogs = values.selectedLogsArray
            posthog.capture('logs exported', { format: 'csv', count: selectedLogs.length, source: 'selection' })
            const columns = getExportColumns(values.attributeColumns)
            const rows = selectedLogs.map((log: ParsedLogMessage) => {
                const row = [
                    log.timestamp,
                    log.severity_text,
                    ...values.attributeColumns.map(
                        (col: string) => log.attributes[col] ?? log.resource_attributes[col] ?? ''
                    ),
                    log.body,
                ]
                if (values.attributeColumns.length === 0) {
                    row.push(JSON.stringify(log.attributes), JSON.stringify(log.resource_attributes))
                }
                return row
            })
            const csv = Papa.unparse([columns, ...rows])
            triggerBlobDownload(new Blob([csv], { type: 'text/csv' }), `logs-${exportTimestamp()}.csv`)
        },
        exportServerSide: async ({ totalLogsCount }) => {
            const query = {
                dateRange: values.utcDateRange,
                searchTerm: values.filters.searchTerm,
                filterGroup: values.filters.filterGroup as PropertyGroupFilter,
                severityLevels: values.filters.severityLevels,
                serviceNames: values.filters.serviceNames,
                orderBy: values.orderBy,
            }
            posthog.capture('logs exported', { format: 'csv', source: 'server', totalLogsCount })
            try {
                await api.logs.exportQuery({
                    query,
                    columns: getExportColumns(values.attributeColumns),
                })
                actions.openSidePanel(SidePanelTab.Exports)
                lemonToast.info('Export starting...')
            } catch (e) {
                lemonToast.error(`Export failed: ${e instanceof Error ? e.message : String(e)}`)
            }
        },
    })),
])
