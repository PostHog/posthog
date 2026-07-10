import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import posthog from 'posthog-js'
import { useEffect, useState } from 'react'

import { FEATURE_FLAGS } from 'lib/constants'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { Spinner } from 'lib/lemon-ui/Spinner/Spinner'
import { userLogic } from 'scenes/userLogic'

import { DashboardType, InsightShortId } from '~/types'

import { SubscriptionBaseProps, urlForSubscription, urlForSubscriptions } from './utils'
import { EditSubscription } from './views/EditSubscription'
import { ManageSubscriptions } from './views/ManageSubscriptions'
import { SubscriptionTabKey, TabbedManageSubscriptions } from './views/TabbedManageSubscriptions'

export interface SubscriptionsModalProps {
    isOpen: boolean
    closeModal: () => void
    subscriptionId: number | 'new' | null
    inline?: boolean
    insightShortId?: InsightShortId
    dashboard?: DashboardType<any> | null
    'data-attr'?: string
}

export function SubscriptionsModal(props: SubscriptionsModalProps): JSX.Element {
    const { closeModal, dashboard, insightShortId, subscriptionId, isOpen, inline, 'data-attr': dataAttr } = props
    const { push } = useActions(router)
    const { userLoading } = useValues(userLogic)

    const dashboardId = dashboard?.id
    const baseProps: SubscriptionBaseProps = { insightShortId, dashboardId }
    // Experiment-gated: the flag resolves to a variant string, so only the test variant gets the new UI.
    const useTabbedOverview = useFeatureFlag('SUBSCRIPTION_TABBED_OVERVIEW', 'test')
    // Owned here (not in the tabbed view) so the selected tab survives the edit round-trip,
    // during which the tabbed view unmounts.
    const [activeTab, setActiveTab] = useState<SubscriptionTabKey>('resource')

    useEffect(() => {
        if (isOpen) {
            // Records which overview variant the user saw, so the tabbed-overview experiment is measurable.
            posthog.capture('subscription_modal_opened', {
                tabbed_overview_variant: posthog.getFeatureFlag(FEATURE_FLAGS.SUBSCRIPTION_TABBED_OVERVIEW) ?? null,
            })
        }
    }, [isOpen])

    if (userLoading) {
        return <Spinner className="text-2xl" />
    }
    return (
        <LemonModal
            onClose={closeModal}
            isOpen={isOpen}
            width={720}
            simple
            title=""
            inline={inline}
            data-attr={dataAttr}
        >
            {!subscriptionId ? (
                useTabbedOverview ? (
                    <TabbedManageSubscriptions
                        {...baseProps}
                        activeTab={activeTab}
                        onChangeTab={setActiveTab}
                        onCancel={closeModal}
                        onSelect={(id) => push(urlForSubscription(id, baseProps))}
                    />
                ) : (
                    <ManageSubscriptions
                        {...baseProps}
                        onCancel={closeModal}
                        onSelect={(id) => push(urlForSubscription(id, baseProps))}
                    />
                )
            ) : (
                <EditSubscription
                    id={subscriptionId}
                    insightShortId={insightShortId}
                    dashboard={dashboard}
                    onCancel={() => push(urlForSubscriptions(baseProps))}
                    onDelete={() => push(urlForSubscriptions(baseProps))}
                />
            )}
        </LemonModal>
    )
}
