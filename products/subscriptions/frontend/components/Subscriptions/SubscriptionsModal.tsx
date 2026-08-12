import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useState } from 'react'

import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { Spinner } from 'lib/lemon-ui/Spinner/Spinner'
import { userLogic } from 'scenes/userLogic'

import { DashboardType, InsightShortId } from '~/types'

import { SubscriptionBaseProps, urlForSubscription, urlForSubscriptions } from './utils'
import { EditSubscription } from './views/EditSubscription'
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
    // Owned here (not in the tabbed view) so the selected tab survives the edit round-trip,
    // during which the tabbed view unmounts.
    const [activeTab, setActiveTab] = useState<SubscriptionTabKey>('resource')

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
                <TabbedManageSubscriptions
                    {...baseProps}
                    activeTab={activeTab}
                    onChangeTab={setActiveTab}
                    onCancel={closeModal}
                    onSelect={(id, resourceType) =>
                        push(
                            urlForSubscription(id, baseProps),
                            resourceType ? { resource_type: resourceType } : undefined
                        )
                    }
                />
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
