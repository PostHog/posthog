import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconPencil, IconSend, IconTrash } from '@posthog/icons'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import type { SceneAction } from '~/layout/scenes/sceneActions/sceneActionModel'
import { SceneActions } from '~/layout/scenes/sceneActions/SceneActions'

import { isSubscriptionEnabled, subscriptionEditHref } from './components/SubscriptionsTable'
import { deleteSubscriptionWithUndo } from './deleteSubscriptionWithUndo'
import { subscriptionSceneLogic } from './subscriptionSceneLogic'
import { SubscriptionTestDeliveryButton } from './SubscriptionTestDeliveryButton'

const RESOURCE_TYPE = 'subscription'

export function SubscriptionSceneMenuBar(): JSX.Element | null {
    const sceneMenuBarEnabled = useFeatureFlag('SCENE_MENU_BAR')
    if (!sceneMenuBarEnabled) {
        return null
    }
    return <SubscriptionSceneMenuBarInner />
}

function SubscriptionSceneMenuBarInner(): JSX.Element {
    const { subscription, subscriptionLoading, deliveringSubscriptionId } = useValues(subscriptionSceneLogic)
    const { setEnabled, deliverSubscription } = useActions(subscriptionSceneLogic)
    const sub = subscription
    const editHref = sub ? subscriptionEditHref(sub) : null

    const actions: SceneAction[] = sub
        ? [
              {
                  group: 'file',
                  section: 'deliver',
                  id: `${RESOURCE_TYPE}-menubar-test-delivery`,
                  label: 'Test delivery',
                  icon: <IconSend />,
                  disabledReason: deliveringSubscriptionId === sub.id ? 'Sending test delivery…' : undefined,
                  onSelect: () => deliverSubscription(sub.id),
                  pinned: { order: 0, variant: 'primary', render: () => <SubscriptionTestDeliveryButton sub={sub} /> },
              },
              {
                  group: 'file',
                  section: 'delete',
                  id: `${RESOURCE_TYPE}-menubar-delete`,
                  label: 'Delete',
                  icon: <IconTrash />,
                  destructive: true,
                  onSelect: () => deleteSubscriptionWithUndo(sub),
              },
              ...(editHref
                  ? ([
                        {
                            group: 'edit',
                            section: 'edit',
                            id: `${RESOURCE_TYPE}-menubar-edit`,
                            label: 'Edit subscription',
                            icon: <IconPencil />,
                            onSelect: () => router.actions.push(editHref),
                            pinned: { order: 1, variant: 'secondary' },
                        },
                    ] satisfies SceneAction[])
                  : []),
              {
                  group: 'edit',
                  section: 'toggles',
                  type: 'checkbox',
                  id: `${RESOURCE_TYPE}-menubar-enabled`,
                  label: 'Enabled',
                  checked: isSubscriptionEnabled(sub),
                  disabledReason: subscriptionLoading ? 'Updating subscription…' : undefined,
                  onCheckedChange: (enabled) => setEnabled({ enabled }),
                  // pinned: data-attr values are wire strings
                  pinned: { order: 0, variant: 'secondary', dataAttr: 'subscription-toggle-enabled' },
              },
          ]
        : []

    return <SceneActions actions={actions} dataAttrKey={RESOURCE_TYPE} />
}
