import { actions, kea, listeners, path, reducers } from 'kea'
import { router, urlToAction } from 'kea-router'

import { syncSearchParams, updateSearchParams } from '@posthog/products-error-tracking/frontend/utils'

import { trackedActionToUrl } from 'lib/logic/scenes/trackedActionToUrl'
import { sqlEditorLogic } from 'scenes/data-warehouse/editor/sqlEditorLogic'
import { SQLEditorMode } from 'scenes/data-warehouse/editor/sqlEditorModes'
import { Params } from 'scenes/sceneTypes'

import type { metricsSceneLogicType } from './metricsSceneLogicType'

export const METRICS_SQL_EDITOR_TAB_ID = 'metrics-sql-editor'

export type MetricsSceneActiveTab = 'viewer' | 'samples' | 'sql'
const VALID_ACTIVE_TABS: MetricsSceneActiveTab[] = ['viewer', 'samples', 'sql']
export const DEFAULT_ACTIVE_TAB: MetricsSceneActiveTab = 'viewer'

export const metricsSceneLogic = kea<metricsSceneLogicType>([
    path(['products', 'metrics', 'frontend', 'metricsSceneLogic']),
    actions({
        setActiveTab: (activeTab: MetricsSceneActiveTab) => ({ activeTab }),
        keepSqlEditorMounted: (editorTabId: string) => ({ editorTabId }),
    }),
    reducers({
        activeTab: [DEFAULT_ACTIVE_TAB as MetricsSceneActiveTab, { setActiveTab: (_, { activeTab }) => activeTab }],
    }),
    urlToAction(({ actions, values, cache }) => {
        const urlToAction = (_: any, params: Params): void => {
            if (cache.isSyncingUrl) {
                return
            }
            const requested = params.activeTab
            if (
                typeof requested === 'string' &&
                VALID_ACTIVE_TABS.includes(requested as MetricsSceneActiveTab) &&
                requested !== values.activeTab
            ) {
                actions.setActiveTab(requested as MetricsSceneActiveTab)
            }
        }
        return { '*': urlToAction }
    }),
    trackedActionToUrl(({ values, cache }) => {
        const syncUrl = (): [string, Params, Record<string, any>, { replace: boolean }] => {
            cache.isSyncingUrl = true
            const result = syncSearchParams(router, (params: Params) => {
                updateSearchParams(params, 'activeTab', values.activeTab, DEFAULT_ACTIVE_TAB)
                return params
            })
            queueMicrotask(() => {
                cache.isSyncingUrl = false
            })
            return result
        }
        return {
            setActiveTab: () => syncUrl(),
        }
    }),
    listeners(({ cache }) => ({
        keepSqlEditorMounted: ({ editorTabId }) => {
            if (cache.sqlEditorTabId === editorTabId) {
                return
            }
            cache.unmountSqlEditor?.()
            cache.sqlEditorTabId = editorTabId
            // Intentionally not cleaned up in beforeUnmount: keeps the embedded sqlEditorLogic
            // alive across navigation so the user's query survives leaving and re-entering /metrics.
            cache.unmountSqlEditor = sqlEditorLogic({ tabId: editorTabId, mode: SQLEditorMode.Embedded }).mount()
        },
    })),
])
