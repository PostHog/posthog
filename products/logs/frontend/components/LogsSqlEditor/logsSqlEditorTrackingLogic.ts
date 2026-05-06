import { connect, kea, key, listeners, path, props } from 'kea'
import posthog from 'posthog-js'

import { SaveAsMenuItem } from 'scenes/data-warehouse/editor/editorSceneLogic'
import { sqlEditorLogic } from 'scenes/data-warehouse/editor/sqlEditorLogic'
import { SQLEditorMode } from 'scenes/data-warehouse/editor/sqlEditorModes'

import type { logsSqlEditorTrackingLogicType } from './logsSqlEditorTrackingLogicType'

export interface LogsSqlEditorTrackingLogicProps {
    sqlEditorTabId: string
}

const captureSaved = (target: SaveAsMenuItem['action']): void => {
    posthog.capture('logs sql query saved', { target })
}

export const logsSqlEditorTrackingLogic = kea<logsSqlEditorTrackingLogicType>([
    path(['products', 'logs', 'frontend', 'components', 'LogsSqlEditor', 'logsSqlEditorTrackingLogic']),
    props({} as LogsSqlEditorTrackingLogicProps),
    key((props) => props.sqlEditorTabId),
    connect((props: LogsSqlEditorTrackingLogicProps) => ({
        actions: [
            sqlEditorLogic({ tabId: props.sqlEditorTabId, mode: SQLEditorMode.Embedded }),
            [
                'runQuery as sqlEditorRunQuery',
                'saveAsViewSubmit as sqlEditorSaveAsViewSubmit',
                'saveAsInsightSubmit as sqlEditorSaveAsInsightSubmit',
                'saveAsEndpointSubmit as sqlEditorSaveAsEndpointSubmit',
            ],
        ],
    })),
    listeners(({ cache }) => ({
        sqlEditorRunQuery: () => {
            // Skip the auto-init runQuery dispatched by LogsSqlEditor's first mount.
            // Trade-off: on revisit (queryInput already set, no auto-init), the user's first
            // manual run is also skipped. Acceptable under-count for an alpha metric.
            if (!cache.firstRunSeen) {
                cache.firstRunSeen = true
                return
            }
            posthog.capture('logs sql query run')
        },
        sqlEditorSaveAsViewSubmit: () => captureSaved('view'),
        sqlEditorSaveAsInsightSubmit: () => captureSaved('insight'),
        sqlEditorSaveAsEndpointSubmit: () => captureSaved('endpoint'),
    })),
])
