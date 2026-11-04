import { useActions, useValues } from 'kea'

import { IconChevronDown, IconEllipsis } from '@posthog/icons'
import { Button, DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@posthog/quill'

import { logsAlertFormLogic } from 'products/logs/frontend/components/LogsAlerting/logsAlertFormLogic'
import { LogsAlertStateIndicator } from 'products/logs/frontend/components/LogsAlerting/LogsAlertStateIndicator'
import {
    LogsAlertConfigurationApi,
    LogsAlertConfigurationStateEnumApi,
} from 'products/logs/frontend/generated/api.schemas'

import { SNOOZE_DURATIONS, logsAlertDetailSceneLogic } from './logsAlertDetailSceneLogic'
import { openDeleteLogsAlertDialog } from './openDeleteLogsAlertDialog'

export interface QuillLogsAlertDetailActionsProps {
    alert: LogsAlertConfigurationApi
    primaryDisabledReason: string | undefined
}

export function QuillLogsAlertDetailActions({
    alert,
    primaryDisabledReason,
}: QuillLogsAlertDetailActionsProps): JSX.Element {
    const { isDraft } = useValues(logsAlertDetailSceneLogic)
    const { toggleEnabled, snoozeAlert, unsnoozeAlert, resetAlert, deleteAlert, enableAlert } =
        useActions(logsAlertDetailSceneLogic)
    const { isAlertFormSubmitting } = useValues(logsAlertFormLogic)
    const { submitAlertForm } = useActions(logsAlertFormLogic)

    const isEnabled = alert.enabled ?? true
    const isBroken = alert.state === LogsAlertConfigurationStateEnumApi.Broken
    const isSnoozed = alert.state === LogsAlertConfigurationStateEnumApi.Snoozed

    const confirmDelete = (): void => openDeleteLogsAlertDialog({ alertName: alert.name, deleteAlert })

    return (
        <div className="flex flex-wrap items-center gap-2">
            {(!isEnabled || alert.state !== LogsAlertConfigurationStateEnumApi.NotFiring) && (
                <LogsAlertStateIndicator
                    state={alert.state}
                    enabled={isEnabled}
                    firstEnabledAt={alert.first_enabled_at}
                    lastErrorMessage={alert.last_error_message}
                    snoozeUntil={alert.snooze_until}
                />
            )}
            {!isDraft && (
                <Button
                    variant={isEnabled ? 'destructive-outline' : 'outline'}
                    onClick={toggleEnabled}
                    disabledReason={isBroken ? 'Reset this alert to re-enable checks' : undefined}
                    data-attr="logs-alert-toggle-enabled"
                >
                    {isEnabled ? 'Disable' : 'Enable'}
                </Button>
            )}
            {isEnabled &&
                (isSnoozed ? (
                    <Button variant="outline" onClick={unsnoozeAlert}>
                        Unsnooze
                    </Button>
                ) : (
                    <DropdownMenu>
                        <DropdownMenuTrigger render={<Button variant="outline" />}>
                            Snooze
                            <IconChevronDown />
                        </DropdownMenuTrigger>
                        <DropdownMenuContent align="end">
                            {SNOOZE_DURATIONS.map((d) => (
                                <DropdownMenuItem key={d.minutes} onClick={() => snoozeAlert(d.minutes)}>
                                    {d.label}
                                </DropdownMenuItem>
                            ))}
                        </DropdownMenuContent>
                    </DropdownMenu>
                ))}
            <Button
                variant="primary"
                onClick={isDraft ? enableAlert : submitAlertForm}
                loading={isAlertFormSubmitting}
                disabledReason={primaryDisabledReason}
                data-attr={isDraft ? 'logs-alert-enable-primary' : 'logs-alert-save-primary'}
            >
                {isDraft ? 'Enable alert' : 'Save'}
            </Button>
            <DropdownMenu>
                <DropdownMenuTrigger
                    render={
                        <Button size="icon" aria-label="More actions" tooltip="More actions" data-attr="more-button" />
                    }
                >
                    <IconEllipsis />
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end">
                    {isBroken && <DropdownMenuItem onClick={resetAlert}>Reset alert</DropdownMenuItem>}
                    <DropdownMenuItem
                        variant="destructive"
                        onClick={confirmDelete}
                        data-attr="logs-alert-detail-delete"
                    >
                        Delete
                    </DropdownMenuItem>
                </DropdownMenuContent>
            </DropdownMenu>
        </div>
    )
}
