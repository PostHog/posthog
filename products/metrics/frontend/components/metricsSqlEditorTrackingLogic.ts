import { connect, kea, key, listeners, path, props } from 'kea'
import posthog from 'posthog-js'

import { SaveAsMenuItem } from 'scenes/data-warehouse/editor/editorSceneLogic'
import { sqlEditorLogic } from 'scenes/data-warehouse/editor/sqlEditorLogic'
import { SQLEditorMode } from 'scenes/data-warehouse/editor/sqlEditorModes'
import { teamLogic } from 'scenes/teamLogic'

import { ProductIntentContext, ProductKey } from '~/queries/schema/schema-general'

import type { metricsSqlEditorTrackingLogicType } from './metricsSqlEditorTrackingLogicType'

export interface MetricsSqlEditorTrackingLogicProps {
    sqlEditorTabId: string
}

export const metricsSqlEditorTrackingLogic = kea<metricsSqlEditorTrackingLogicType>([
    path(['products', 'metrics', 'frontend', 'components', 'metricsSqlEditorTrackingLogic']),
    props({} as MetricsSqlEditorTrackingLogicProps),
    key((props) => props.sqlEditorTabId),
    connect((props: MetricsSqlEditorTrackingLogicProps) => ({
        actions: [
            sqlEditorLogic({ tabId: props.sqlEditorTabId, mode: SQLEditorMode.Embedded }),
            [
                'runQuery as sqlEditorRunQuery',
                'saveAsViewSubmit as sqlEditorSaveAsViewSubmit',
                'saveAsInsightSubmit as sqlEditorSaveAsInsightSubmit',
                'saveAsEndpointSubmit as sqlEditorSaveAsEndpointSubmit',
            ],
            teamLogic,
            ['addProductIntent'],
        ],
    })),
    listeners(({ actions, cache }) => {
        const trackSaved = (target: SaveAsMenuItem['action']): void => {
            posthog.capture('metrics sql query saved', { target })
            actions.addProductIntent({
                product_type: ProductKey.METRICS,
                intent_context: ProductIntentContext.METRICS_QUERY_SAVED,
                metadata: { target },
            })
        }
        return {
            sqlEditorRunQuery: () => {
                // Skip the auto-init runQuery dispatched by MetricsSqlEditor's first mount.
                // Trade-off: on revisit (queryInput already set, no auto-init), the user's first
                // manual run is also skipped. Acceptable under-count for an alpha metric.
                if (!cache.firstRunSeen) {
                    cache.firstRunSeen = true
                    return
                }
                posthog.capture('metrics sql query run')
                actions.addProductIntent({
                    product_type: ProductKey.METRICS,
                    intent_context: ProductIntentContext.METRICS_SQL_QUERY_RUN,
                })
            },
            sqlEditorSaveAsViewSubmit: () => trackSaved('view'),
            sqlEditorSaveAsInsightSubmit: () => trackSaved('insight'),
            sqlEditorSaveAsEndpointSubmit: () => trackSaved('endpoint'),
        }
    }),
])
