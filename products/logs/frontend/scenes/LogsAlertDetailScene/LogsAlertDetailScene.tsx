import { BindLogic, useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { IconChevronDown, IconTestTube } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonDialog, LemonModal, LemonTabs } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonMenu, LemonMenuOverlay } from 'lib/lemon-ui/LemonMenu/LemonMenu'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { LogSeverityLevel } from '~/queries/schema/schema-general'
import { FilterLogicalOperator, UniversalFiltersGroup } from '~/types'

import { LogsAlertEventHistoryContent } from 'products/logs/frontend/components/LogsAlerting/LogsAlertEventHistory'
import { LogsAlertForm } from 'products/logs/frontend/components/LogsAlerting/LogsAlertForm'
import { logsAlertFormLogic } from 'products/logs/frontend/components/LogsAlerting/logsAlertFormLogic'
import { logsAlertNotificationLogic } from 'products/logs/frontend/components/LogsAlerting/logsAlertNotificationLogic'
import { LogsAlertNotifications } from 'products/logs/frontend/components/LogsAlerting/LogsAlertNotifications'
import { LogsAlertSimulation } from 'products/logs/frontend/components/LogsAlerting/LogsAlertSimulation'
import { LogsAlertStateIndicator } from 'products/logs/frontend/components/LogsAlerting/LogsAlertStateIndicator'
import { LogsViewer } from 'products/logs/frontend/components/LogsViewer'
import {
    LogsAlertConfigurationApi,
    LogsAlertConfigurationStateEnumApi,
} from 'products/logs/frontend/generated/api.schemas'

import {
    LogsAlertDetailSceneLogicProps,
    LogsAlertDetailTab,
    SNOOZE_DURATIONS,
    logsAlertDetailSceneLogic,
} from './logsAlertDetailSceneLogic'

export const scene: SceneExport<LogsAlertDetailSceneLogicProps> = {
    component: LogsAlertDetailScene,
    logic: logsAlertDetailSceneLogic,
    paramsToProps: ({ params: { id } }) => ({ id }),
}

export function LogsAlertDetailScene(): JSX.Element {
    const { alert, alertId, alertLoading, activeTab } = useValues(logsAlertDetailSceneLogic)
    const { setActiveTab } = useActions(logsAlertDetailSceneLogic)

    const formLogicProps = { alert: alert ?? ({ id: alertId } as LogsAlertConfigurationApi) }
    const notifLogicProps = { alertId }
    const { isSimulationPanelOpen } = useValues(logsAlertFormLogic(formLogicProps))
    const { closeSimulationPanel } = useActions(logsAlertFormLogic(formLogicProps))

    if (!alert && !alertLoading) {
        return (
            <SceneContent>
                <div className="p-8 text-muted text-center">Alert not found.</div>
            </SceneContent>
        )
    }

    return (
        <BindLogic logic={logsAlertFormLogic} props={formLogicProps}>
            <BindLogic logic={logsAlertNotificationLogic} props={notifLogicProps}>
                <SceneContent>
                    <AlertHeader />
                    <div className="flex flex-col gap-4 p-4">
                        {alert && <AlertStatusBand />}
                        <LemonTabs
                            activeKey={activeTab}
                            onChange={(key) => setActiveTab(key as LogsAlertDetailTab)}
                            tabs={[
                                {
                                    key: 'configuration',
                                    label: 'Configuration',
                                    content: <ConfigurationTab />,
                                },
                                {
                                    key: 'notifications',
                                    label: 'Notifications',
                                    content: <NotificationsTab />,
                                },
                                {
                                    key: 'history',
                                    label: 'History',
                                    content: alert ? <LogsAlertEventHistoryContent alert={alert} /> : <></>,
                                },
                                {
                                    key: 'logs',
                                    label: 'Observed logs',
                                    content: alert ? <ObservedLogsTab alert={alert} /> : <></>,
                                },
                            ]}
                        />
                    </div>
                    <LemonModal
                        isOpen={isSimulationPanelOpen}
                        onClose={closeSimulationPanel}
                        title="Alert simulation"
                        description="Run the alert against historical data to preview when it would have fired. Includes threshold evaluation, N-of-M noise reduction, and cooldown."
                        width={960}
                    >
                        <LogsAlertSimulation />
                    </LemonModal>
                </SceneContent>
            </BindLogic>
        </BindLogic>
    )
}

function AlertHeader(): JSX.Element {
    const { alert, alertLoading } = useValues(logsAlertDetailSceneLogic)
    const { toggleEnabled, snoozeAlert, unsnoozeAlert, resetAlert, deleteAlert, renameAlert } =
        useActions(logsAlertDetailSceneLogic)

    const { isAlertFormSubmitting, alertFormChanged } = useValues(logsAlertFormLogic)
    const { submitAlertForm } = useActions(logsAlertFormLogic)
    const { pendingNotifications } = useValues(logsAlertNotificationLogic)

    const isEnabled = alert?.enabled ?? true
    const isBroken = alert?.state === LogsAlertConfigurationStateEnumApi.Broken
    const isSnoozed = alert?.state === LogsAlertConfigurationStateEnumApi.Snoozed

    return (
        <SceneTitleSection
            name={alert?.name}
            resourceType={{ type: 'logs' }}
            isLoading={alertLoading && !alert}
            canEdit={!!alert}
            onNameChange={renameAlert}
            renameDebounceMs={300}
            actions={
                alert ? (
                    <div className="flex items-center gap-2">
                        {(!isEnabled || alert.state !== LogsAlertConfigurationStateEnumApi.NotFiring) && (
                            <LogsAlertStateIndicator
                                state={alert.state}
                                enabled={isEnabled}
                                lastErrorMessage={alert.last_error_message}
                                snoozeUntil={alert.snooze_until}
                            />
                        )}
                        <LemonButton
                            size="small"
                            type="secondary"
                            status={isEnabled ? 'danger' : undefined}
                            onClick={toggleEnabled}
                            disabledReason={isBroken ? 'Reset this alert to re-enable checks' : undefined}
                        >
                            {isEnabled ? 'Disable' : 'Enable'}
                        </LemonButton>
                        {isSnoozed ? (
                            <LemonButton size="small" type="secondary" onClick={unsnoozeAlert}>
                                Unsnooze
                            </LemonButton>
                        ) : (
                            <LemonMenu
                                placement="bottom-end"
                                items={SNOOZE_DURATIONS.map((d) => ({
                                    label: d.label,
                                    onClick: () => snoozeAlert(d.minutes),
                                }))}
                            >
                                <LemonButton size="small" type="secondary" sideIcon={<IconChevronDown />}>
                                    Snooze
                                </LemonButton>
                            </LemonMenu>
                        )}
                        <LemonButton
                            size="small"
                            type="primary"
                            onClick={submitAlertForm}
                            loading={isAlertFormSubmitting}
                            disabledReason={
                                !alertFormChanged && pendingNotifications.length === 0
                                    ? 'No changes to save'
                                    : undefined
                            }
                        >
                            Save
                        </LemonButton>
                        <More
                            overlay={
                                <LemonMenuOverlay
                                    items={[
                                        ...(isBroken ? [{ label: 'Reset alert', onClick: resetAlert }] : []),
                                        {
                                            label: 'Delete',
                                            status: 'danger' as const,
                                            onClick: () => {
                                                LemonDialog.open({
                                                    title: `Delete "${alert.name}"?`,
                                                    description:
                                                        'This alert will be permanently deleted. This action cannot be undone.',
                                                    primaryButton: {
                                                        children: 'Delete',
                                                        type: 'primary',
                                                        status: 'danger',
                                                        onClick: deleteAlert,
                                                    },
                                                    secondaryButton: { children: 'Cancel' },
                                                })
                                            },
                                        },
                                    ]}
                                />
                            }
                        />
                    </div>
                ) : undefined
            }
        />
    )
}

function AlertStatusBand(): JSX.Element | null {
    const { alert } = useValues(logsAlertDetailSceneLogic)
    const { resetAlert, unsnoozeAlert, toggleEnabled, setActiveTab } = useActions(logsAlertDetailSceneLogic)
    const { destinationGroups, existingHogFunctionsLoading } = useValues(logsAlertNotificationLogic)

    if (!alert) {
        return null
    }

    const banners: JSX.Element[] = []

    if (!alert.enabled && alert.state !== LogsAlertConfigurationStateEnumApi.Broken) {
        banners.push(
            <LemonBanner key="disabled" type="warning" action={{ children: 'Enable', onClick: toggleEnabled }}>
                This alert is disabled — no checks are running.
            </LemonBanner>
        )
    }

    if (alert.state === LogsAlertConfigurationStateEnumApi.Broken) {
        banners.push(
            <LemonBanner key="broken" type="error" action={{ children: 'Reset alert', onClick: resetAlert }}>
                <div className="font-semibold">
                    Auto-disabled after {alert.consecutive_failures ?? 'repeated'} consecutive check failures.
                </div>
                {alert.last_error_message && (
                    <div className="text-xs font-mono mt-1 whitespace-pre-wrap break-words">
                        {alert.last_error_message}
                    </div>
                )}
            </LemonBanner>
        )
    }

    if (alert.state === LogsAlertConfigurationStateEnumApi.Snoozed && alert.snooze_until) {
        banners.push(
            <LemonBanner key="snoozed" type="info" action={{ children: 'Unsnooze', onClick: unsnoozeAlert }}>
                Snoozed until <TZLabel time={alert.snooze_until} timestampStyle="absolute" />.
            </LemonBanner>
        )
    }

    if (alert.state === LogsAlertConfigurationStateEnumApi.Firing) {
        banners.push(
            <LemonBanner key="firing" type="error">
                <span className="font-semibold">Alert is currently firing.</span>
                {alert.last_checked_at && (
                    <span className="text-xs ml-2">
                        Last checked <TZLabel time={alert.last_checked_at} />.
                    </span>
                )}
            </LemonBanner>
        )
    }

    if (alert.enabled && !existingHogFunctionsLoading && destinationGroups.length === 0) {
        banners.push(
            <LemonBanner
                key="no-destinations"
                type="warning"
                action={{ children: 'Add notification', onClick: () => setActiveTab('notifications') }}
            >
                No notifications configured — this alert will fire silently.
            </LemonBanner>
        )
    }

    if (banners.length === 0) {
        return null
    }

    return <div className="flex flex-col gap-2">{banners}</div>
}

function ConfigurationTab(): JSX.Element {
    const { alert } = useValues(logsAlertDetailSceneLogic)
    const { isSimulationPanelOpen } = useValues(logsAlertFormLogic)
    const { openSimulationPanel } = useActions(logsAlertFormLogic)
    const formLogicProps = { alert: alert ?? null }

    if (!alert) {
        return <div className="p-4 text-muted">Loading…</div>
    }

    return (
        <div className="flex flex-col gap-4">
            <div>
                <LemonButton
                    type="secondary"
                    icon={<IconTestTube />}
                    onClick={openSimulationPanel}
                    active={isSimulationPanelOpen}
                    tooltip="Run this alert against historical data to see when it would have fired"
                >
                    Simulate
                </LemonButton>
            </div>
            <Form
                logic={logsAlertFormLogic}
                props={formLogicProps}
                formKey="alertForm"
                enableFormOnSubmit
                className="flex flex-col gap-6"
            >
                <LogsAlertForm />
            </Form>
        </div>
    )
}

function NotificationsTab(): JSX.Element {
    const { alert } = useValues(logsAlertDetailSceneLogic)

    if (!alert) {
        return <div className="p-4 text-muted">Loading…</div>
    }

    return (
        <div className="flex flex-col gap-4 max-w-xl">
            <LogsAlertNotifications alertId={alert.id} />
        </div>
    )
}

function ObservedLogsTab({ alert }: { alert: LogsAlertConfigurationApi }): JSX.Element {
    const filters = (alert.filters ?? {}) as Record<string, unknown>
    const initialFilters = {
        severityLevels: ((filters.severityLevels as string[] | undefined) ?? []) as LogSeverityLevel[],
        serviceNames: (filters.serviceNames as string[] | undefined) ?? [],
        filterGroup: (filters.filterGroup as UniversalFiltersGroup | undefined) ?? {
            type: FilterLogicalOperator.And,
            values: [],
        },
    }

    return (
        <div className="h-[calc(100vh-20rem)] min-h-[400px]">
            <LogsViewer id={`alert-${alert.id}-logs`} initialFilters={initialFilters} showSavedViewsButton={false} />
        </div>
    )
}
