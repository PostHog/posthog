import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { IconExternal, IconTrash } from '@posthog/icons'
import { LemonButton, LemonDialog, LemonSkeleton, LemonSwitch, LemonTag, Tooltip } from '@posthog/lemon-ui'
import { Badge, Button } from '@posthog/quill'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { slackIntegrationLogic } from 'lib/integrations/slackIntegrationLogic'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { HogFunctionType } from '~/types'

import {
    CUSTOM_MESSAGE_TAG,
    getHogFunctionEventKind,
    LOGS_ALERT_EVENT_KIND_META,
    logsAlertEventKindsFor,
    LogsAlertEventKind,
    resolveGroupLabel,
} from 'products/logs/frontend/components/LogsAlerting/logsAlertUtils'

import { DestinationRecentSends } from './DestinationRecentSends'
import {
    LogsAlertNotificationDetailSceneLogicProps,
    logsAlertNotificationDetailSceneLogic,
} from './logsAlertNotificationDetailSceneLogic'

export const scene: SceneExport<LogsAlertNotificationDetailSceneLogicProps> = {
    component: LogsAlertNotificationDetailScene,
    logic: logsAlertNotificationDetailSceneLogic,
    paramsToProps: ({ params: { id, hogFunctionId } }) => ({ alertId: id, hogFunctionId }),
}

export function LogsAlertNotificationDetailScene(): JSX.Element {
    const {
        alert,
        alertLoading,
        destinationGroup,
        hogFunctionsLoading,
        hasLoaded,
        hogFunctionsError,
        isDeleting,
        togglingHogFunctionIds,
        alertId,
        hogFunctionId,
        firstSlackIntegration,
        messageCustomized,
        recentSends,
        recentSendsLoading,
        recentSendsError,
        eventLabelByHogFunctionId,
    } = useValues(logsAlertNotificationDetailSceneLogic)
    const customizationEnabled = useFeatureFlag('ALERTS_DESTINATION_CUSTOMIZATION')
    const { deleteDestination, loadHogFunctions, loadRecentSends, setHogFunctionEnabled } = useActions(
        logsAlertNotificationDetailSceneLogic
    )

    const slackLogic = slackIntegrationLogic({ id: firstSlackIntegration?.id ?? 0 })
    const { slackChannels } = useValues(slackLogic)
    const { loadAllSlackChannels } = useActions(slackLogic)
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    useEffect(() => {
        if (firstSlackIntegration) {
            loadAllSlackChannels()
        }
    }, [firstSlackIntegration?.id, loadAllSlackChannels, firstSlackIntegration])

    const loading = alertLoading || hogFunctionsLoading
    const displayLabel = destinationGroup ? resolveGroupLabel(destinationGroup, slackChannels) : 'Destination'
    const editorReturnTo = encodeURIComponent(urls.logsAlertNotificationDetail(alertId, hogFunctionId))
    const confirmRemoveDestination = (): void => {
        LemonDialog.open({
            title: `Remove ${displayLabel}?`,
            description:
                'This will delete all notification functions for this destination. The underlying hog functions will be soft-deleted.',
            primaryButton: {
                children: 'Remove',
                type: 'primary',
                status: 'danger',
                onClick: () => deleteDestination(displayLabel),
                'data-attr': 'logs-alert-destination-delete-confirm',
            },
            secondaryButton: { children: 'Cancel' },
        })
    }

    if (hogFunctionsError) {
        return (
            <SceneContent>
                <SceneTitleSection
                    name="Couldn't load destination"
                    resourceType={{ type: 'logs' }}
                    actions={
                        todayRailNav ? (
                            <div className="flex flex-wrap items-center gap-2">
                                <Button
                                    variant="outline"
                                    render={<LinkPrimitive to={urls.logsAlertDetail(alertId, 'notifications')} />}
                                >
                                    Back to alert
                                </Button>
                                <Button variant="primary" onClick={() => loadHogFunctions()}>
                                    Retry
                                </Button>
                            </div>
                        ) : (
                            <div className="flex items-center gap-2">
                                <LemonButton type="secondary" to={urls.logsAlertDetail(alertId, 'notifications')}>
                                    Back to alert
                                </LemonButton>
                                <LemonButton type="primary" onClick={() => loadHogFunctions()}>
                                    Retry
                                </LemonButton>
                            </div>
                        )
                    }
                />
                <div className="p-8 text-muted text-center">
                    Failed to load destination details: {hogFunctionsError}
                </div>
            </SceneContent>
        )
    }

    if (hasLoaded && !destinationGroup) {
        return (
            <SceneContent>
                <SceneTitleSection
                    name="Destination not found"
                    resourceType={{ type: 'logs' }}
                    actions={
                        todayRailNav ? (
                            <Button
                                variant="outline"
                                render={<LinkPrimitive to={urls.logsAlertDetail(alertId, 'notifications')} />}
                            >
                                Back to alert
                            </Button>
                        ) : (
                            <LemonButton type="secondary" to={urls.logsAlertDetail(alertId, 'notifications')}>
                                Back to alert
                            </LemonButton>
                        )
                    }
                />
                <div className="p-8 text-muted text-center">
                    This notification destination no longer exists for this alert.
                </div>
            </SceneContent>
        )
    }

    const kindToFn = new Map<LogsAlertEventKind, HogFunctionType>()
    for (const hf of destinationGroup?.hogFunctions ?? []) {
        const kind = getHogFunctionEventKind(hf)
        if (kind) {
            kindToFn.set(kind, hf)
        }
    }

    return (
        <SceneContent>
            <SceneTitleSection
                name={destinationGroup ? displayLabel : 'Destination'}
                description={alert ? `Notifications fired for alert "${alert.name}".` : undefined}
                resourceType={{ type: 'logs' }}
                isLoading={loading && !destinationGroup}
                actions={
                    destinationGroup && todayRailNav ? (
                        <div className="flex flex-wrap items-center gap-2">
                            <Badge variant={destinationGroup.enabled ? 'success' : 'default'}>
                                {destinationGroup.enabled ? 'Active' : 'Paused'}
                            </Badge>
                            <Button
                                variant="destructive-outline"
                                disabledReason={isDeleting ? 'Removing…' : undefined}
                                onClick={confirmRemoveDestination}
                                data-attr="logs-alert-destination-delete"
                            >
                                <IconTrash />
                                Remove destination
                            </Button>
                        </div>
                    ) : destinationGroup ? (
                        <div className="flex items-center gap-2">
                            <LemonTag type={destinationGroup.enabled ? 'success' : 'default'}>
                                {destinationGroup.enabled ? 'Active' : 'Paused'}
                            </LemonTag>
                            {customizationEnabled && messageCustomized ? (
                                <Tooltip title={CUSTOM_MESSAGE_TAG.tooltip}>
                                    <LemonTag>{CUSTOM_MESSAGE_TAG.label}</LemonTag>
                                </Tooltip>
                            ) : null}
                            <LemonButton
                                size="small"
                                type="secondary"
                                status="danger"
                                icon={<IconTrash />}
                                disabledReason={isDeleting ? 'Removing…' : undefined}
                                onClick={confirmRemoveDestination}
                                data-attr="logs-alert-destination-delete"
                            >
                                Remove destination
                            </LemonButton>
                        </div>
                    ) : undefined
                }
            />
            <div className="flex flex-col gap-4 p-4 max-w-3xl">
                <p className="text-sm text-muted m-0">
                    These hog functions only run for this alert. Open one to edit the message body, headers, filters, or
                    destination details for the matching lifecycle event.
                    {customizationEnabled
                        ? ' Changes apply to notifications sent after you save. If the alert is firing now, its resolve message may still use the earlier version.'
                        : null}
                </p>

                {loading ? (
                    <LemonSkeleton className="h-16" repeat={4} />
                ) : (
                    <div className="flex flex-col gap-2">
                        {logsAlertEventKindsFor(destinationGroup?.type ?? 'webhook').map((kind) => {
                            const fn = kindToFn.get(kind)
                            const meta = LOGS_ALERT_EVENT_KIND_META[kind]
                            const isToggling = !!fn && togglingHogFunctionIds.includes(fn.id)
                            return (
                                <div key={kind} className="flex items-center justify-between border rounded p-3 gap-3">
                                    <div className="flex-1 min-w-0">
                                        <div className="flex items-center gap-2 flex-wrap">
                                            <span className="text-sm font-semibold">{meta.label}</span>
                                            {!fn && (
                                                <LemonTag type="warning" size="small">
                                                    Missing
                                                </LemonTag>
                                            )}
                                        </div>
                                        {fn ? <div className="text-xs text-muted mt-1 truncate">{fn.name}</div> : null}
                                        <div className="text-xs text-muted mt-1">{meta.description}</div>
                                    </div>
                                    <div className="flex items-center gap-2 shrink-0">
                                        {fn ? (
                                            <LemonSwitch
                                                checked={fn.enabled}
                                                disabledReason={isToggling ? 'Saving…' : undefined}
                                                onChange={(checked) => setHogFunctionEnabled(fn.id, checked)}
                                                label={fn.enabled ? 'Active' : 'Paused'}
                                                data-attr={`logs-alert-destination-toggle-${kind}`}
                                            />
                                        ) : null}
                                        <LemonButton
                                            size="small"
                                            type="secondary"
                                            icon={<IconExternal />}
                                            to={
                                                fn ? `${urls.hogFunction(fn.id)}?returnTo=${editorReturnTo}` : undefined
                                            }
                                            tooltip={fn ? 'Open hog function editor' : undefined}
                                            disabledReason={fn ? undefined : 'No hog function for this event kind'}
                                            data-attr={`logs-alert-destination-open-${kind}`}
                                        >
                                            Open editor
                                        </LemonButton>
                                    </div>
                                </div>
                            )
                        })}
                    </div>
                )}

                {customizationEnabled && destinationGroup ? (
                    <DestinationRecentSends
                        sends={recentSends}
                        loading={recentSendsLoading}
                        error={recentSendsError}
                        onRetry={loadRecentSends}
                        eventLabels={eventLabelByHogFunctionId}
                    />
                ) : null}
            </div>
        </SceneContent>
    )
}
