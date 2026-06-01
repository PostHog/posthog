import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'
import { subscriptions } from 'kea-subscriptions'
import posthog from 'posthog-js'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { Scene } from 'scenes/sceneTypes'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { Breadcrumb, HogFunctionType, IntegrationType } from '~/types'

import {
    buildLogsAlertFilterConfig,
    groupLogsAlertDestinations,
    LogsAlertDestinationGroup,
} from 'products/logs/frontend/components/LogsAlerting/logsAlertUtils'
import { logsAlertsDestinationsDeleteCreate, logsAlertsRetrieve } from 'products/logs/frontend/generated/api'
import { LogsAlertConfigurationApi } from 'products/logs/frontend/generated/api.schemas'

import type { logsAlertNotificationDetailSceneLogicType } from './logsAlertNotificationDetailSceneLogicType'

export interface LogsAlertNotificationDetailSceneLogicProps {
    alertId: string
    hogFunctionId: string
}

export const logsAlertNotificationDetailSceneLogic = kea<logsAlertNotificationDetailSceneLogicType>([
    path((key) => [
        'products',
        'logs',
        'frontend',
        'scenes',
        'LogsAlertNotificationDetailScene',
        'logsAlertNotificationDetailSceneLogic',
        key,
    ]),
    props({} as LogsAlertNotificationDetailSceneLogicProps),
    key((props) => `${props.alertId}:${props.hogFunctionId}`),

    connect({
        values: [teamLogic, ['currentTeamId'], integrationsLogic, ['slackIntegrations']],
    }),

    actions({
        deleteDestination: (displayLabel: string) => ({ displayLabel }),
        deleteDestinationDone: true,
        setHogFunctionEnabled: (hogFunctionId: string, enabled: boolean) => ({ hogFunctionId, enabled }),
    }),

    reducers({
        hasLoaded: [
            false,
            {
                loadHogFunctionsSuccess: () => true,
            },
        ],
        hogFunctionsError: [
            null as string | null,
            {
                loadHogFunctions: () => null,
                loadHogFunctionsSuccess: () => null,
                loadHogFunctionsFailure: (_, { error }: { error: string }) => error || 'Failed to load destinations',
            },
        ],
        isDeleting: [
            false,
            {
                deleteDestination: () => true,
                deleteDestinationDone: () => false,
            },
        ],
        togglingHogFunctionIds: [
            [] as string[],
            {
                setHogFunctionEnabled: (state, { hogFunctionId }) =>
                    state.includes(hogFunctionId) ? state : [...state, hogFunctionId],
                loadHogFunctionsSuccess: () => [],
                loadHogFunctionsFailure: () => [],
            },
        ],
    }),

    loaders(({ values, props }) => ({
        alert: [
            null as LogsAlertConfigurationApi | null,
            {
                loadAlert: async () => {
                    if (!values.currentTeamId) {
                        return null
                    }
                    return logsAlertsRetrieve(String(values.currentTeamId), props.alertId)
                },
            },
        ],
        hogFunctions: [
            [] as HogFunctionType[],
            {
                loadHogFunctions: async () => {
                    if (!values.currentTeamId) {
                        return []
                    }
                    const response = await api.hogFunctions.list({
                        types: ['internal_destination'],
                        filter_groups: [buildLogsAlertFilterConfig(props.alertId)],
                        full: true,
                    })
                    return response.results
                },
            },
        ],
    })),

    selectors({
        alertId: [() => [(_, props) => props.alertId], (alertId: string): string => alertId],
        hogFunctionId: [() => [(_, props) => props.hogFunctionId], (id: string): string => id],
        firstSlackIntegration: [
            (s) => [s.slackIntegrations],
            (slackIntegrations: IntegrationType[] | undefined): IntegrationType | undefined => slackIntegrations?.[0],
        ],
        destinationGroup: [
            (s) => [s.hogFunctions, s.hogFunctionId],
            (hogFunctions: HogFunctionType[], hogFunctionId: string): LogsAlertDestinationGroup | null => {
                const groups = groupLogsAlertDestinations(hogFunctions, () => null)
                return groups.find((g) => g.hogFunctions.some((hf) => hf.id === hogFunctionId)) ?? null
            },
        ],
        breadcrumbs: [
            (s) => [s.alert, s.destinationGroup, s.alertId],
            (
                alert: LogsAlertConfigurationApi | null,
                group: LogsAlertDestinationGroup | null,
                alertId: string
            ): Breadcrumb[] => [
                {
                    key: Scene.Logs,
                    name: 'Logs',
                    path: `${urls.logs()}?activeTab=alerts`,
                    iconType: 'logs',
                },
                {
                    key: Scene.LogsAlertDetail,
                    name: alert?.name ?? 'Alert',
                    path: urls.logsAlertDetail(alertId, 'notifications'),
                    iconType: 'logs',
                },
                {
                    key: Scene.LogsAlertNotificationDetail,
                    name: group?.label ?? 'Destination',
                    iconType: 'logs',
                },
            ],
        ],
    }),

    listeners(({ actions, values, props }) => ({
        deleteDestination: async ({ displayLabel }) => {
            const group = values.destinationGroup
            if (!group || !values.currentTeamId) {
                actions.deleteDestinationDone()
                return
            }
            try {
                await logsAlertsDestinationsDeleteCreate(String(values.currentTeamId), props.alertId, {
                    hog_function_ids: group.hogFunctions.map((hf) => hf.id),
                })
                lemonToast.success(`Removed ${displayLabel}`)
                router.actions.push(urls.logsAlertDetail(props.alertId, 'notifications'))
            } catch (error: unknown) {
                posthog.captureException(error, { tag: 'logs-alert-destination-delete' })
                const detail =
                    (error as { detail?: string; message?: string })?.detail ?? (error as { message?: string })?.message
                lemonToast.error(
                    detail ? `Failed to remove ${displayLabel}: ${detail}` : `Failed to remove ${displayLabel}`
                )
            } finally {
                actions.deleteDestinationDone()
            }
        },
        setHogFunctionEnabled: async ({ hogFunctionId, enabled }) => {
            try {
                await api.hogFunctions.update(hogFunctionId, { enabled })
            } catch (error: unknown) {
                posthog.captureException(error, { tag: 'logs-alert-hog-function-toggle' })
                const detail =
                    (error as { detail?: string; message?: string })?.detail ?? (error as { message?: string })?.message
                lemonToast.error(
                    detail
                        ? `Failed to ${enabled ? 'enable' : 'pause'} notification: ${detail}`
                        : `Failed to ${enabled ? 'enable' : 'pause'} notification`
                )
            }
            // Refresh whether the update succeeded or failed — the success path picks up the new state,
            // the failure path reverts the UI to the server's truth. `togglingHogFunctionIds` clears
            // on loadHogFunctions{Success,Failure}, so the LemonSwitch stays disabled until the
            // refreshed list lands (prevents the double-click race against stale local state).
            actions.loadHogFunctions()
        },
    })),

    subscriptions(({ values, actions }) => ({
        currentTeamId: (currentTeamId: number | null) => {
            if (!currentTeamId) {
                return
            }
            if (!values.alert && !values.alertLoading) {
                actions.loadAlert()
            }
            if (!values.hasLoaded && !values.hogFunctionsLoading) {
                actions.loadHogFunctions()
            }
        },
    })),

    afterMount(({ actions, values }) => {
        if (values.currentTeamId) {
            actions.loadAlert()
            actions.loadHogFunctions()
        }
    }),
])
