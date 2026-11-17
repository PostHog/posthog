import { useActions, useValues } from 'kea'

import { IconBell, IconCheck, IconRefresh, IconTrash } from '@posthog/icons'
import { Button } from '@posthog/quill'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import type { SceneAction } from '~/layout/scenes/sceneActions/sceneActionModel'
import { SceneActions } from '~/layout/scenes/sceneActions/SceneActions'

import { logsAlertFormLogic } from 'products/logs/frontend/components/LogsAlerting/logsAlertFormLogic'
import { LogsAlertStateIndicator } from 'products/logs/frontend/components/LogsAlerting/LogsAlertStateIndicator'
import {
    LogsAlertConfigurationApi,
    LogsAlertConfigurationStateEnumApi,
} from 'products/logs/frontend/generated/api.schemas'

import { SNOOZE_DURATIONS, logsAlertDetailSceneLogic } from './logsAlertDetailSceneLogic'
import { openDeleteLogsAlertDialog } from './openDeleteLogsAlertDialog'

const RESOURCE_TYPE = 'logs-alert'

interface LogsAlertDetailSceneMenuBarProps {
    alert: LogsAlertConfigurationApi
    primaryDisabledReason: string | undefined
}

export function LogsAlertDetailSceneMenuBar(props: LogsAlertDetailSceneMenuBarProps): JSX.Element | null {
    const enabled = useFeatureFlag('SCENE_MENU_BAR')
    return enabled ? <LogsAlertDetailSceneMenuBarInner {...props} /> : null
}

function LogsAlertDetailSceneMenuBarInner({
    alert,
    primaryDisabledReason,
}: LogsAlertDetailSceneMenuBarProps): JSX.Element {
    const { isDraft } = useValues(logsAlertDetailSceneLogic)
    const { toggleEnabled, snoozeAlert, unsnoozeAlert, resetAlert, deleteAlert, enableAlert } =
        useActions(logsAlertDetailSceneLogic)
    const { isAlertFormSubmitting } = useValues(logsAlertFormLogic)
    const { submitAlertForm } = useActions(logsAlertFormLogic)

    const isEnabled = alert.enabled ?? true
    const isBroken = alert.state === LogsAlertConfigurationStateEnumApi.Broken
    const isSnoozed = alert.state === LogsAlertConfigurationStateEnumApi.Snoozed
    const toggleDisabledReason = isBroken ? 'Reset this alert to re-enable checks' : undefined
    const savingReason = isAlertFormSubmitting ? 'Saving the alert' : undefined

    const actions: SceneAction[] = [
        {
            group: 'edit',
            section: 'save',
            id: isDraft ? `${RESOURCE_TYPE}-menubar-enable-alert` : `${RESOURCE_TYPE}-menubar-save`,
            label: isDraft ? 'Enable alert' : 'Save',
            icon: <IconCheck />,
            disabledReason: primaryDisabledReason ?? savingReason,
            onSelect: isDraft ? enableAlert : submitAlertForm,
            pinned: {
                order: 3,
                variant: 'primary',
                // The state indicator has no action of its own, so it rides with the primary button.
                render: () => (
                    <div className="flex items-center gap-2">
                        {(!isEnabled || alert.state !== LogsAlertConfigurationStateEnumApi.NotFiring) && (
                            <LogsAlertStateIndicator
                                state={alert.state}
                                enabled={isEnabled}
                                firstEnabledAt={alert.first_enabled_at}
                                lastErrorMessage={alert.last_error_message}
                                snoozeUntil={alert.snooze_until}
                            />
                        )}
                        <Button
                            variant="primary"
                            onClick={isDraft ? enableAlert : submitAlertForm}
                            loading={isAlertFormSubmitting}
                            disabledReason={primaryDisabledReason}
                            data-attr={isDraft ? 'logs-alert-enable-primary' : 'logs-alert-save-primary'}
                        >
                            {isDraft ? 'Enable alert' : 'Save'}
                        </Button>
                    </div>
                ),
            },
        },
        ...(!isDraft
            ? ([
                  {
                      group: 'edit',
                      section: 'state',
                      type: 'checkbox',
                      id: `${RESOURCE_TYPE}-menubar-enabled`,
                      label: 'Enabled',
                      checked: isEnabled,
                      disabledReason: toggleDisabledReason,
                      onCheckedChange: () => toggleEnabled(),
                      pinned: {
                          order: 1,
                          variant: 'secondary',
                          render: () => (
                              <Button
                                  variant={isEnabled ? 'destructive-outline' : 'outline'}
                                  onClick={toggleEnabled}
                                  disabledReason={toggleDisabledReason}
                                  data-attr="logs-alert-toggle-enabled"
                              >
                                  {isEnabled ? 'Disable' : 'Enable'}
                              </Button>
                          ),
                      },
                  },
              ] satisfies SceneAction[])
            : []),
        ...(isEnabled && isSnoozed
            ? ([
                  {
                      group: 'edit',
                      section: 'state',
                      id: `${RESOURCE_TYPE}-menubar-unsnooze`,
                      label: 'Unsnooze',
                      icon: <IconBell />,
                      onSelect: unsnoozeAlert,
                      pinned: { order: 2, variant: 'secondary' },
                  },
              ] satisfies SceneAction[])
            : []),
        ...(isEnabled && !isSnoozed
            ? ([
                  {
                      group: 'edit',
                      section: 'state',
                      type: 'submenu',
                      id: `${RESOURCE_TYPE}-menubar-snooze`,
                      label: 'Snooze',
                      icon: <IconBell />,
                      items: SNOOZE_DURATIONS.map((duration) => ({
                          id: `${RESOURCE_TYPE}-menubar-snooze-${duration.minutes}`,
                          label: duration.label,
                          onSelect: () => snoozeAlert(duration.minutes),
                      })),
                      pinned: { order: 2, variant: 'secondary' },
                  },
              ] satisfies SceneAction[])
            : []),
        ...(isBroken
            ? ([
                  {
                      group: 'edit',
                      section: 'state',
                      id: `${RESOURCE_TYPE}-menubar-reset`,
                      label: 'Reset alert',
                      icon: <IconRefresh />,
                      onSelect: resetAlert,
                  },
              ] satisfies SceneAction[])
            : []),
        {
            group: 'file',
            section: 'delete',
            id: 'logs-alert-detail-delete',
            label: 'Delete alert',
            icon: <IconTrash />,
            destructive: true,
            onSelect: () => openDeleteLogsAlertDialog({ alertName: alert.name, deleteAlert }),
        },
    ]

    return <SceneActions actions={actions} dataAttrKey={RESOURCE_TYPE} />
}
