import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { FEATURE_FLAGS } from 'lib/constants'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { Spinner } from 'lib/lemon-ui/Spinner/Spinner'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { userLogic } from 'scenes/userLogic'

import { DashboardType, InsightShortId } from '~/types'

import { SubscriptionBaseProps, urlForSubscription, urlForSubscriptions } from './utils'
import { EditSubscription } from './views/EditSubscription'
import { ManageSubscriptions } from './views/ManageSubscriptions'
import { TabbedManageSubscriptions } from './views/TabbedManageSubscriptions'

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
    const { featureFlags } = useValues(featureFlagLogic)

    const dashboardId = dashboard?.id
    const baseProps: SubscriptionBaseProps = { insightShortId, dashboardId }
    // Experiment-gated: the flag resolves to a variant string, so only the test variant gets the new UI.
    const useTabbedOverview = featureFlags[FEATURE_FLAGS.SUBSCRIPTION_TABBED_OVERVIEW] === 'test'

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
