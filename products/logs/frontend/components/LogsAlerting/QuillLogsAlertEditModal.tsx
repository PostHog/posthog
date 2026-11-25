import { BindLogic, useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { useId } from 'react'

import { IconBell, IconGraph, IconList, IconPulse, IconTarget } from '@posthog/icons'
import { Button, Dialog, DialogContent, Field, FieldLabel, Switch, Text } from '@posthog/quill'

import { closesIntoLemonPopover } from 'lib/components/QuillSurface/closesIntoLemonPopover'
import { QuillSurfaceContext } from 'lib/ui/QuillSurface/quillSurfaceContext'
import { urls } from 'scenes/urls'

import { QuillAlertEditor } from 'products/alerts/frontend/components/QuillAlertEditor'
import { QuillAlertEditorFormDetails } from 'products/alerts/frontend/components/QuillAlertEditorFormDetails'
import { QuillSnoozeButton } from 'products/alerts/frontend/components/QuillSnoozeButton'
import { EditAlertTab } from 'products/alerts/frontend/views/EditAlertModal/EditAlertTabs'
import { QuillEditAlertTabs } from 'products/alerts/frontend/views/EditAlertModal/QuillEditAlertTabs'
import { platformAlertDestinationsLogic } from 'products/alerts_platform/frontend/destinations/platformAlertDestinationsLogic'
import { PlatformAlertStateTimeline } from 'products/alerts_platform/frontend/PlatformAlertStateTimeline'
import { LogsAlertConfigurationApi } from 'products/logs/frontend/generated/api.schemas'

import { confirmDeleteLogsAlert } from './confirmDeleteLogsAlert'
import { logsAlertDestinationsLogicProps } from './logsAlertDestinations'
import { buildLogsAlertEditSummary } from './logsAlertEditorModel'
import { logsAlertFormLogic } from './logsAlertFormLogic'
import { logsAlertingLogic } from './logsAlertingLogic'
import { LogsAlertNotifications } from './LogsAlertNotifications'
import { QuillLogsAlertEventHistory } from './QuillLogsAlertEventHistory'
import { QuillLogsAlertFilters } from './QuillLogsAlertFilters'
import { QuillLogsAlertRegroupConfirmModal } from './QuillLogsAlertRegroupConfirmModal'
import { QuillLogsAlertSimulation } from './QuillLogsAlertSimulation'
import { QuillLogsAlertStateIndicator } from './QuillLogsAlertStateIndicator'
import { QuillLogsAlertTrigger } from './QuillLogsAlertTrigger'

interface QuillLogsAlertEditModalProps {
    alert: LogsAlertConfigurationApi | null
    onClose: () => void
}

export function QuillLogsAlertEditModal({ alert, onClose }: QuillLogsAlertEditModalProps): JSX.Element {
    return (
        <Dialog
            open={alert !== null}
            // The service and filter pickers open Lemon popovers that portal outside the dialog. A modal dialog would
            // make them inert and pull focus back, so the dialog stays non-modal and ignores clicks that land in them.
            modal={false}
            onOpenChange={(open, details) => {
                if (closesIntoLemonPopover(open, details)) {
                    details.cancel()
                    return
                }
                if (!open) {
                    onClose()
                }
            }}
        >
            <DialogContent className="sm:max-w-225">
                {alert ? <QuillLogsAlertEditModalContent alert={alert} onClose={onClose} /> : null}
            </DialogContent>
        </Dialog>
    )
}

function QuillLogsAlertEditModalContent({
    alert,
    onClose,
}: {
    alert: LogsAlertConfigurationApi
    onClose: () => void
}): JSX.Element {
    const formLogicProps = { alert, onSubmitSuccess: onClose }
    const notificationLogicProps = logsAlertDestinationsLogicProps(alert.id)
    const { isAlertFormSubmitting, alertFormChanged, alertFormErrors, alertForm } = useValues(
        logsAlertFormLogic(formLogicProps)
    )
    const { touchAlertFormField } = useActions(logsAlertFormLogic(formLogicProps))
    const { destinations } = useValues(platformAlertDestinationsLogic(notificationLogicProps))
    const { snoozingAlertIds } = useValues(logsAlertingLogic)
    const { deleteAlert, snoozeAlertUntil, toggleAlertEnabled, unsnoozeAlert } = useActions(logsAlertingLogic)
    const enabledSwitchId = useId()
    const nameError = alertFormErrors.name as string | undefined
    const summary = buildLogsAlertEditSummary(alertForm, destinations)

    const tabs: EditAlertTab[] = [
        {
            key: 'monitor',
            summarySection: 'monitor',
            label: (
                <>
                    <IconPulse />
                    Monitor
                </>
            ),
            content: (
                <div className="flex flex-col gap-3 pt-3">
                    <QuillAlertEditorFormDetails nameError={nameError} />
                    <div className="max-w-2xl">
                        <QuillLogsAlertFilters />
                    </div>
                </div>
            ),
        },
        {
            key: 'trigger',
            summarySection: 'monitor',
            label: (
                <>
                    <IconTarget />
                    Trigger
                </>
            ),
            content: (
                <div className="flex max-w-2xl flex-col gap-6 pt-3">
                    <QuillLogsAlertTrigger />
                    <QuillLogsAlertSimulation embedded />
                </div>
            ),
        },
        {
            key: 'notify',
            summarySection: 'notify',
            label: (
                <>
                    <IconBell />
                    Notify
                </>
            ),
            content: (
                <div className="pt-3">
                    <QuillSurfaceContext.Provider value>
                        <LogsAlertNotifications alertId={alert.id} />
                    </QuillSurfaceContext.Provider>
                </div>
            ),
        },
        {
            key: 'history',
            label: (
                <>
                    <IconGraph />
                    History
                </>
            ),
            content: (
                <div className="pt-3">
                    <QuillLogsAlertEventHistory alert={alert} />
                </div>
            ),
        },
        {
            key: 'observed-logs',
            label: (
                <>
                    <IconList />
                    Observed logs
                </>
            ),
            link: urls.logsAlertDetail(alert.id, 'logs'),
        },
    ]

    const leadingActions = (
        <div className="flex flex-wrap items-center gap-2">
            <Button
                variant="destructive-outline"
                onClick={() => confirmDeleteLogsAlert(alert, (alertId) => deleteAlert(alertId, onClose))}
            >
                Delete alert
            </Button>
            {(alert.enabled ?? true) ? (
                <QuillSnoozeButton
                    onChange={(snoozeUntil) => snoozeAlertUntil(alert.id, snoozeUntil)}
                    onClear={alert.snooze_until ? () => unsnoozeAlert(alert.id) : undefined}
                    value={alert.snooze_until ?? undefined}
                    disabledReason={snoozingAlertIds.has(alert.id) ? 'Updating snooze' : undefined}
                />
            ) : null}
        </div>
    )

    return (
        <BindLogic logic={logsAlertFormLogic} props={formLogicProps}>
            <BindLogic logic={platformAlertDestinationsLogic} props={notificationLogicProps}>
                <Form
                    logic={logsAlertFormLogic}
                    props={formLogicProps}
                    formKey="alertForm"
                    enableFormOnSubmit
                    className="contents"
                >
                    <QuillAlertEditor
                        title="Edit alert"
                        isEditing
                        isSubmitting={isAlertFormSubmitting}
                        hasChanges={alertFormChanged}
                        onSubmitAttempted={() => touchAlertFormField('name')}
                        leadingActions={leadingActions}
                        trailingActions={
                            <Field orientation="horizontal" className="w-fit">
                                <Switch
                                    id={enabledSwitchId}
                                    checked={alert.enabled ?? true}
                                    onCheckedChange={() => toggleAlertEnabled(alert)}
                                />
                                <FieldLabel htmlFor={enabledSwitchId}>Enabled</FieldLabel>
                            </Field>
                        }
                    >
                        <QuillEditAlertTabs
                            summary={summary}
                            summaryHeader={
                                <div className="flex flex-wrap items-center justify-between gap-3">
                                    <Text size="xs" weight="medium" render={<span />}>
                                        Current status
                                    </Text>
                                    <QuillLogsAlertStateIndicator
                                        state={alert.state}
                                        enabled={alert.enabled ?? true}
                                        firstEnabledAt={alert.first_enabled_at}
                                        lastErrorMessage={alert.last_error_message}
                                        snoozeUntil={alert.snooze_until}
                                    />
                                </div>
                            }
                            statusNode={
                                <PlatformAlertStateTimeline
                                    timeline={alert.state_timeline}
                                    className="h-8 w-full"
                                    showAxis
                                />
                            }
                            tabs={tabs}
                            showCadence={false}
                        />
                    </QuillAlertEditor>
                </Form>
                <QuillLogsAlertRegroupConfirmModal />
            </BindLogic>
        </BindLogic>
    )
}
