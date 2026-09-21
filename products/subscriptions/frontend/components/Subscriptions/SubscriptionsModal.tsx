import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import posthog from 'posthog-js'
import { useEffect, useRef, useState } from 'react'

import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { Spinner } from 'lib/lemon-ui/Spinner/Spinner'
import { userLogic } from 'scenes/userLogic'

import { DashboardType, InsightShortId, SubscriptionResourceTypes } from '~/types'

import { subscriptionLogic } from './subscriptionLogic'
import { SubscriptionWizard } from './SubscriptionWizard'
import {
    requestSubscriptionWizardCancellation,
    SubscriptionBaseProps,
    urlForSubscription,
    urlForSubscriptions,
} from './utils'
import { EditSubscription } from './views/EditSubscription'
import { SubscriptionTabKey, TabbedManageSubscriptions } from './views/TabbedManageSubscriptions'

export interface SubscriptionsModalProps {
    isOpen: boolean
    closeModal: () => void
    subscriptionId?: number | null
    inline?: boolean
    insightShortId?: InsightShortId
    insightName?: string
    dashboard?: DashboardType<any> | null
    'data-attr'?: string
}

export function SubscriptionsModal(props: SubscriptionsModalProps): JSX.Element {
    const {
        closeModal,
        dashboard,
        insightShortId,
        insightName,
        subscriptionId,
        isOpen,
        inline,
        'data-attr': dataAttr,
    } = props
    const { push } = useActions(router)
    const { userLoading } = useValues(userLogic)
    const { searchParams } = useValues(router)

    const dashboardId = dashboard?.id
    const isAiPrompt = searchParams.resource_type === SubscriptionResourceTypes.AiPrompt
    const baseProps: SubscriptionBaseProps = { insightShortId, dashboardId }
    const isWizard = subscriptionId === undefined
    const modalWasOpen = useRef(false)
    useEffect(() => {
        if (!isOpen) {
            modalWasOpen.current = false
            return
        }
        if (!isWizard || modalWasOpen.current) {
            return
        }
        modalWasOpen.current = true
        posthog.capture('subscription creation modal opened', {
            creation_source: 'wizard',
            resource_type: isAiPrompt ? 'ai' : dashboard ? 'dashboard' : 'insight',
        })
    }, [dashboard, isAiPrompt, isOpen, isWizard])
    const cancelWizard = (): void => push(urlForSubscriptions(baseProps))
    const requestWizardCancel = (): void => {
        const wizardForm = subscriptionLogic.findMounted({
            id: 'new',
            insightShortId,
            dashboardId,
            creationSource: 'wizard',
        })
        if (!wizardForm) {
            cancelWizard()
            return
        }
        requestSubscriptionWizardCancellation({
            onCancel: cancelWizard,
            resetSubscription: () => wizardForm.actions.resetSubscription(),
            subscriptionChanged: wizardForm.values.subscriptionChanged,
        })
    }
    // Owned here (not in the tabbed view) so the selected tab survives the edit round-trip,
    // during which the tabbed view unmounts.
    const [activeTab, setActiveTab] = useState<SubscriptionTabKey>('resource')

    if (userLoading) {
        return <Spinner className="text-2xl" />
    }
    return (
        <LemonModal
            onClose={isWizard ? requestWizardCancel : closeModal}
            isOpen={isOpen}
            width={720}
            simple
            title={isWizard ? 'New subscription' : ''}
            inline={inline}
            data-attr={dataAttr}
        >
            {isWizard ? (
                <SubscriptionWizard
                    insightShortId={insightShortId}
                    insightName={insightName}
                    dashboard={dashboard}
                    onCancel={cancelWizard}
                />
            ) : subscriptionId != null ? (
                <EditSubscription
                    id={subscriptionId}
                    insightShortId={insightShortId}
                    dashboard={dashboard}
                    onCancel={() => push(urlForSubscriptions(baseProps))}
                    onDelete={() => push(urlForSubscriptions(baseProps))}
                />
            ) : (
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
            )}
        </LemonModal>
    )
}
