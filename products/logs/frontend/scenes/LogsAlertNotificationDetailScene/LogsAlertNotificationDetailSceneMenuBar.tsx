import { router } from 'kea-router'

import { IconArrowLeft, IconRefresh, IconTrash } from '@posthog/icons'
import { Button } from '@posthog/quill'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { urls } from 'scenes/urls'

import type { SceneAction } from '~/layout/scenes/sceneActions/sceneActionModel'
import { SceneActions } from '~/layout/scenes/sceneActions/SceneActions'

const RESOURCE_TYPE = 'logs-alert-destination'

interface LogsAlertNotificationDetailSceneMenuBarProps {
    alertId: string
    onRetry?: () => void
    onRemove?: () => void
    removeDisabledReason?: string
    /** The destination's status badge, which the title row shows beside the remove button. */
    statusBadge?: JSX.Element
}

export function LogsAlertNotificationDetailSceneMenuBar(
    props: LogsAlertNotificationDetailSceneMenuBarProps
): JSX.Element | null {
    const enabled = useFeatureFlag('SCENE_MENU_BAR')
    return enabled ? <LogsAlertNotificationDetailSceneMenuBarInner {...props} /> : null
}

function LogsAlertNotificationDetailSceneMenuBarInner({
    alertId,
    onRetry,
    onRemove,
    removeDisabledReason,
    statusBadge,
}: LogsAlertNotificationDetailSceneMenuBarProps): JSX.Element {
    const actions: SceneAction[] = [
        ...(onRetry
            ? ([
                  {
                      group: 'file',
                      id: `${RESOURCE_TYPE}-menubar-retry`,
                      label: 'Retry',
                      icon: <IconRefresh />,
                      onSelect: onRetry,
                      pinned: { order: 2, variant: 'primary' },
                  },
              ] satisfies SceneAction[])
            : []),
        {
            group: 'view',
            id: `${RESOURCE_TYPE}-menubar-back-to-alert`,
            label: 'Back to alert',
            icon: <IconArrowLeft />,
            onSelect: () => router.actions.push(urls.logsAlertDetail(alertId, 'notifications')),
            pinned: onRemove ? undefined : { order: 1, variant: 'secondary' },
        },
        ...(onRemove
            ? ([
                  {
                      group: 'file',
                      section: 'delete',
                      id: `${RESOURCE_TYPE}-menubar-remove`,
                      label: 'Remove destination',
                      icon: <IconTrash />,
                      destructive: true,
                      disabledReason: removeDisabledReason,
                      onSelect: onRemove,
                      pinned: {
                          order: 1,
                          variant: 'secondary',
                          render: () => (
                              <div className="flex items-center gap-2">
                                  {statusBadge}
                                  <Button
                                      variant="destructive-outline"
                                      disabledReason={removeDisabledReason}
                                      onClick={onRemove}
                                      data-attr="logs-alert-destination-delete"
                                  >
                                      <IconTrash />
                                      Remove destination
                                  </Button>
                              </div>
                          ),
                      },
                  },
              ] satisfies SceneAction[])
            : []),
    ]

    return <SceneActions actions={actions} dataAttrKey={RESOURCE_TYPE} />
}
