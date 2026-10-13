import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconEllipsis } from '@posthog/icons'
import { LemonButton, LemonMenu } from '@posthog/lemon-ui'

import { LemonSwitch } from 'lib/lemon-ui/LemonSwitch'
import { LemonTab, LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { deleteWithUndo } from 'lib/utils/deleteWithUndo'
import { getCurrentTeamId } from 'lib/utils/getAppContext'
import { sceneConfigurations } from 'scenes/scenes'
import { Scene, SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'

import type { SubscriptionApi } from 'products/subscriptions/frontend/generated/api.schemas'

import { subscriptionsEmptyState } from '../emptyState/subscriptionsEmptyState'
import { SubscriptionsFiltersBar } from './components/SubscriptionsFiltersBar'
import { SubscriptionsSceneModal } from './components/SubscriptionsSceneModal'
import {
    SubscriptionsTable,
    isSubscriptionEnabled,
    subscriptionEditHref,
    subscriptionName,
} from './components/SubscriptionsTable'
import { SubscriptionsTab, subscriptionsSceneLogic } from './subscriptionsSceneLogic'

function SubscriptionEnabledSwitch({ sub }: { sub: SubscriptionApi }): JSX.Element {
    const { setSubscriptionEnabled } = useActions(subscriptionsSceneLogic)
    const { togglingEnabledIds } = useValues(subscriptionsSceneLogic)
    const enabled = isSubscriptionEnabled(sub)
    return (
        <LemonSwitch
            checked={enabled}
            onChange={(newEnabled) => setSubscriptionEnabled(sub.id, newEnabled)}
            loading={Boolean(togglingEnabledIds[sub.id])}
            aria-label={`${enabled ? 'Disable' : 'Enable'} ${subscriptionName(sub)}`}
            data-attr="subscription-row-toggle-enabled"
        />
    )
}

function SubscriptionsRowActions({ sub }: { sub: SubscriptionApi }): JSX.Element {
    const { push } = useActions(router)
    const { deleteSubscriptionSuccess, deliverSubscription } = useActions(subscriptionsSceneLogic)
    const { deliveringSubscriptionId, togglingEnabledIds } = useValues(subscriptionsSceneLogic)
    const href = subscriptionEditHref(sub)
    const isDelivering = deliveringSubscriptionId === sub.id
    const isToggling = Boolean(togglingEnabledIds[sub.id])
    const enabled = isSubscriptionEnabled(sub)

    return (
        <LemonMenu
            items={[
                ...(href
                    ? [
                          {
                              label: 'Edit subscription',
                              onClick: () => push(href),
                          },
                      ]
                    : []),
                ...(enabled
                    ? [
                          {
                              label: 'Test delivery',
                              'data-attr': 'subscription-list-item-manual-deliver',
                              disabledReason: isDelivering ? 'Sending test delivery…' : null,
                              onClick: () => deliverSubscription(sub.id),
                          },
                      ]
                    : []),
                {
                    label: 'Delete',
                    status: 'danger' as const,
                    onClick: () =>
                        void deleteWithUndo({
                            endpoint: `projects/${String(getCurrentTeamId())}/subscriptions`,
                            object: {
                                id: sub.id,
                                name: subscriptionName(sub),
                            },
                            callback: () => deleteSubscriptionSuccess(),
                        }),
                },
            ]}
        >
            <LemonButton
                icon={isDelivering || isToggling ? <Spinner /> : <IconEllipsis />}
                size="small"
                aria-label="Subscription actions"
                disabled={isDelivering || isToggling}
            />
        </LemonMenu>
    )
}

export function SubscriptionsScene(): JSX.Element {
    const {
        subscriptions,
        subscriptionsLoading,
        pagination,
        currentTab,
        subscriptionsSorting,
        aiSubscriptionsAvailable,
    } = useValues(subscriptionsSceneLogic)
    const { setCurrentTab, setSubscriptionsSorting } = useActions(subscriptionsSceneLogic)

    const subscriptionTabs: LemonTab<SubscriptionsTab>[] = [
        { key: SubscriptionsTab.All, label: 'All subscriptions' },
        { key: SubscriptionsTab.Mine, label: 'My subscriptions' },
        { key: SubscriptionsTab.Dashboard, label: 'Dashboard' },
        { key: SubscriptionsTab.Insight, label: 'Insight' },
        ...(aiSubscriptionsAvailable ? [{ key: SubscriptionsTab.AI, label: 'AI prompt' }] : []),
    ]
    return (
        <SceneContent>
            <SceneTitleSection
                name={sceneConfigurations[Scene.Subscriptions].name}
                description={sceneConfigurations[Scene.Subscriptions].description}
                resourceType={{ type: 'inbox' }}
                actions={
                    <LemonButton
                        type="primary"
                        data-attr="new-subscription-button"
                        onClick={() => router.actions.push(urls.subscriptionNew())}
                    >
                        New subscription
                    </LemonButton>
                }
            />
            <LemonTabs
                activeKey={currentTab}
                onChange={(newKey) => setCurrentTab(newKey)}
                tabs={subscriptionTabs}
                sceneInset
            />
            <div className="py-8 flex-1 min-h-0 flex flex-col gap-4 max-w-full">
                <SubscriptionsFiltersBar />
                <SubscriptionsTable
                    dataSource={subscriptions}
                    loading={subscriptionsLoading}
                    pagination={pagination}
                    sorting={subscriptionsSorting}
                    onSort={setSubscriptionsSorting}
                    renderRowActions={(sub) => <SubscriptionsRowActions sub={sub} />}
                    renderEnabledToggle={(sub) => <SubscriptionEnabledSwitch sub={sub} />}
                />
            </div>
            <SubscriptionsSceneModal />
        </SceneContent>
    )
}

export const scene: SceneExport = {
    component: SubscriptionsScene,
    logic: subscriptionsSceneLogic,
    productKey: ProductKey.SUBSCRIPTIONS,
    emptyState: subscriptionsEmptyState,
}
