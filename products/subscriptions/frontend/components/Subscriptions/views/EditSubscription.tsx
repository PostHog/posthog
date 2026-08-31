import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import type { ReactNode } from 'react'

import { IconChevronLeft, IconSend } from '@posthog/icons'
import { Link } from '@posthog/lemon-ui'

import { UsageLimitPaywall } from 'lib/components/PayGateMini/UsageLimitPaywall'
import { TZLabel } from 'lib/components/TZLabel'
import { UserActivityIndicator } from 'lib/components/UserActivityIndicator/UserActivityIndicator'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel/LemonLabel'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { Spinner } from 'lib/lemon-ui/Spinner/Spinner'
import { preflightLogic } from 'lib/logic/preflightLogic'
import { organizationLogic } from 'scenes/organizationLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { SubscriptionFreeTierLimit } from '~/queries/schema/schema-general'
import { AvailableFeature, DashboardType, InsightShortId, SubscriptionResourceTypes } from '~/types'

import type { SubscriptionDeliveryApi } from 'products/subscriptions/frontend/generated/api.schemas'

import { ProactiveSubscriptionFields } from '../ProactiveSubscriptionFields'
import { subscriptionCountLogic } from '../subscriptionCountLogic'
import {
    getSubscriptionEditTabs,
    normalizeSubscriptionEditTab,
    shouldShowSubscriptionActions,
    shouldWaitForSubscriptionActions,
} from '../subscriptionFormNavigation'
import { subscriptionLogic } from '../subscriptionLogic'
import type { SubscriptionLogicProps } from '../subscriptionLogic'
import { SubscriptionNotifySection } from '../SubscriptionNotifySection'
import { SubscriptionReportSection } from '../SubscriptionReportSection'
import { SubscriptionScheduleSection } from '../SubscriptionScheduleSection'
import { SubscriptionSettingsSection } from '../SubscriptionSettingsSection'
import { subscriptionsLogic } from '../subscriptionsLogic'
import { getAiSubscriptionGate, isFreeTierCreateAtLimit } from '../utils'

const AI_NOT_ALLOWED_REASON = 'Enable AI data processing in your Organization settings to use AI subscriptions.'

function AiConsentGateMessage(): JSX.Element {
    return (
        <>
            {AI_NOT_ALLOWED_REASON}{' '}
            <Link to={urls.settings('organization-details', 'organization-ai-consent')}>Manage AI data processing</Link>
        </>
    )
}

function LastDeliveryStatus({
    lastDelivery,
    loading,
    failed,
}: {
    lastDelivery: SubscriptionDeliveryApi | null
    loading: boolean
    failed: boolean
}): JSX.Element {
    if (loading) {
        return <LemonSkeleton className="inline-block h-4 w-32" />
    }
    if (failed) {
        return <>Last run unavailable</>
    }
    if (!lastDelivery) {
        return <>No deliveries yet</>
    }
    return (
        <>
            Last run:{' '}
            <TZLabel
                time={lastDelivery.finished_at ?? lastDelivery.created_at}
                formatDate="ddd, MMM D"
                formatTime="h:mm A"
                timestampStyle="absolute"
            />
        </>
    )
}

interface EditSubscriptionProps {
    id: number | 'new'
    insightShortId?: InsightShortId
    insightName?: string
    dashboard?: DashboardType<any> | null
    onCancel: () => void
    onDelete: () => void
}

export function EditSubscription(props: EditSubscriptionProps): JSX.Element {
    if (props.id !== 'new') {
        return <EditSubscriptionForm {...props} />
    }
    return (
        <SubscriptionCreationGate onCancel={props.onCancel}>
            <EditSubscriptionForm {...props} />
        </SubscriptionCreationGate>
    )
}

export function SubscriptionCreationGate({
    onCancel,
    children,
}: {
    onCancel: () => void
    children: ReactNode
}): JSX.Element {
    const { hasAvailableFeature } = useValues(userLogic)
    const { subscriptionCount, subscriptionCountLoading } = useValues(subscriptionCountLogic)

    if (hasAvailableFeature(AvailableFeature.SUBSCRIPTIONS)) {
        return <>{children}</>
    }
    if (subscriptionCount === null && subscriptionCountLoading) {
        return (
            <div className="flex min-h-0 flex-1 items-center justify-center py-8">
                <Spinner className="text-2xl" />
            </div>
        )
    }
    if (isFreeTierCreateAtLimit(subscriptionCount)) {
        return (
            <div className="flex min-h-0 flex-1 flex-col">
                <LemonModal.Header>
                    <div className="flex items-center gap-2">
                        <LemonButton icon={<IconChevronLeft />} onClick={onCancel} size="xsmall" />
                        <h3>New subscription</h3>
                    </div>
                </LemonModal.Header>
                <UsageLimitPaywall
                    title="Subscription limit reached"
                    description={
                        <>
                            <Link to={urls.subscriptions()}>Delete an existing subscription</Link> or upgrade your plan
                            to add more.
                        </>
                    }
                    limit={SubscriptionFreeTierLimit.COUNT}
                    currentUsage={subscriptionCount ?? undefined}
                    unit="subscriptions allowed on your plan"
                    background={false}
                    className="min-h-0 flex-1 justify-center py-8"
                />
            </div>
        )
    }
    return <>{children}</>
}

export function SubscriptionFormSkeleton(): JSX.Element {
    return (
        <div className="flex min-h-[36rem] flex-col gap-4 p-4">
            {[
                ['w-1/3', 'w-full'],
                ['w-1/4', 'w-full'],
            ].map(([label, field], index) => (
                <div key={index} className="flex flex-col gap-2">
                    <LemonSkeleton className={`h-4 ${label}`} />
                    <LemonSkeleton className={`h-9 ${field}`} />
                </div>
            ))}
            <div className="flex flex-col gap-2">
                <LemonSkeleton className="h-4 w-1/3" />
                <LemonSkeleton className="h-24 w-full" />
            </div>
        </div>
    )
}

function EditSubscriptionForm({
    id,
    insightShortId,
    insightName,
    dashboard,
    onCancel,
    onDelete,
}: EditSubscriptionProps): JSX.Element {
    const dashboardId = dashboard?.id
    const logicProps: SubscriptionLogicProps = {
        id,
        insightShortId,
        insightName,
        dashboardId,
        dashboardName: dashboard?.name,
    }
    const logic = subscriptionLogic(logicProps)
    const subscriptions = subscriptionsLogic({ insightShortId, dashboardId })
    const {
        subscription,
        subscriptionLoading,
        isSubscriptionSubmitting,
        subscriptionChanged,
        subscriptionEditTab,
        lastDelivery,
        lastDeliveryLoadFailed,
        lastDeliveryLoading,
        testDeliveryLoading,
        previewLoading,
        previewError,
        previewImageUrl,
        proactiveConfigurationOptions,
        proactiveConfigurationOptionsLoading,
        proactiveConfigurationOptionsLoadFailed,
    } = useValues(logic)
    const { generatePreview, sendTestDelivery, setSubscriptionEditTab } = useActions(logic)
    const { deleteSubscription } = useActions(subscriptions)
    const { preflight, siteUrlMisconfigured } = useValues(preflightLogic)
    const { currentOrganization } = useValues(organizationLogic)
    const aiSubscriptionsEnabled = useFeatureFlag('SUBSCRIPTION_AI_PROMPT')
    const aiContextsEnabled = useFeatureFlag('SUBSCRIPTION_AI_CONTEXTS')
    const redesignedEditorEnabled = useFeatureFlag('SUBSCRIPTION_CREATION_WIZARD', 'test')
    const isEditing = id !== 'new'
    const isAiPrompt = subscription?.resource_type === SubscriptionResourceTypes.AiPrompt
    const isParentless = !insightShortId && !dashboardId
    const subscriptionLoaded = Boolean(subscription?.target_type)

    if (subscriptionLoading || (isEditing && !subscriptionLoaded)) {
        return <SubscriptionFormSkeleton />
    }
    if (!subscription) {
        return (
            <div className="p-4 text-center">
                <h2>Not found</h2>
                <p>This subscription could not be found. It may have been deleted.</p>
            </div>
        )
    }

    const aiGate = getAiSubscriptionGate({
        isAiPrompt,
        isParentless,
        isEditing,
        aiConsentApproved: Boolean(currentOrganization?.is_ai_data_processing_approved),
        isCloud: Boolean(preflight?.cloud),
        isDebug: Boolean(preflight?.is_debug),
        aiFlagEnabled: Boolean(aiSubscriptionsEnabled),
    })
    const actionsVisibility = {
        subscription,
        proactiveConfigurationOptions,
        proactiveConfigurationOptionsLoading,
        proactiveConfigurationOptionsLoadFailed,
    }
    if (redesignedEditorEnabled && isEditing && shouldWaitForSubscriptionActions(actionsVisibility)) {
        return <SubscriptionFormSkeleton />
    }
    const showActions = shouldShowSubscriptionActions(actionsVisibility)
    const editTabs = getSubscriptionEditTabs(showActions)
    const activeEditTab = normalizeSubscriptionEditTab(subscriptionEditTab, showActions)
    const consentMessage = <AiConsentGateMessage />
    const reportSection = (
        <SubscriptionReportSection
            logicProps={logicProps}
            subscription={subscription}
            dashboard={dashboard}
            insightName={insightName}
            aiContextsEnabled={Boolean(aiContextsEnabled)}
            selectionReady={!isEditing || subscriptionLoaded}
            showResourceTypeToggle={aiGate.showResourceTypeToggle}
            aiOptionDisabledReason={!aiGate.aiOptionEnabled ? AI_NOT_ALLOWED_REASON : undefined}
            aiConsentHint={aiGate.showConsentHint ? consentMessage : undefined}
            aiConsentMessage={aiGate.showAiFormConsentBanner ? consentMessage : undefined}
        />
    )
    const previewSection =
        insightShortId && !isAiPrompt ? (
            <div className="flex flex-col gap-2 border-t pt-4">
                <LemonLabel>Preview</LemonLabel>
                <div className="rounded border p-2">
                    <LemonButton
                        type="secondary"
                        htmlType="button"
                        onClick={generatePreview}
                        loading={previewLoading}
                        disabled={previewLoading}
                        size="small"
                    >
                        Generate preview
                    </LemonButton>
                    {previewError ? (
                        <LemonBanner type="error" className="mt-2">
                            {previewError}
                        </LemonBanner>
                    ) : null}
                    {previewImageUrl ? (
                        <img
                            src={previewImageUrl}
                            alt="Subscription export preview"
                            className="mt-2 w-full rounded border"
                        />
                    ) : null}
                </div>
            </div>
        ) : null
    const deliveryStatus = isEditing ? (
        <div className="flex flex-wrap items-center justify-between gap-2 border-t pt-4">
            <div className="text-sm text-secondary">
                <LastDeliveryStatus
                    lastDelivery={lastDelivery}
                    loading={lastDeliveryLoading}
                    failed={lastDeliveryLoadFailed}
                />
                {' · '}
                <Link to={urls.subscription(id)}>View history</Link>
            </div>
            <LemonButton
                type="secondary"
                htmlType="button"
                size="small"
                icon={<IconSend />}
                onClick={sendTestDelivery}
                loading={testDeliveryLoading}
                disabled={testDeliveryLoading}
                disabledReason={
                    subscription.enabled === false
                        ? 'Re-enable this subscription before sending a test delivery'
                        : undefined
                }
            >
                Send test delivery
            </LemonButton>
        </div>
    ) : null
    const contentByTab = {
        content: (
            <div className="flex flex-col gap-5">
                {reportSection}
                {previewSection}
            </div>
        ),
        actions: <ProactiveSubscriptionFields logicProps={logicProps} subscription={subscription} />,
        delivery: (
            <div className="flex flex-col gap-5">
                <SubscriptionNotifySection logicProps={logicProps} subscription={subscription} />
                <div className="border-t pt-4">
                    <SubscriptionScheduleSection logicProps={logicProps} />
                </div>
                {deliveryStatus}
            </div>
        ),
        settings: (
            <SubscriptionSettingsSection logicProps={logicProps} subscription={subscription} showEnabled={isEditing} />
        ),
    } as const

    const deleteCurrentSubscription = (): void => {
        if (isEditing) {
            deleteSubscription(id)
            onDelete()
        }
    }

    return (
        <Form
            logic={subscriptionLogic}
            props={logicProps}
            formKey="subscription"
            enableFormOnSubmit
            className="flex min-h-0 min-w-0 flex-1 flex-col"
        >
            <LemonModal.Header>
                <div className="flex items-center gap-2">
                    <LemonButton icon={<IconChevronLeft />} onClick={onCancel} size="xsmall" />
                    <h3>{isEditing ? 'Edit subscription' : 'New subscription'}</h3>
                </div>
            </LemonModal.Header>

            <LemonModal.Content className="min-h-0 min-w-0 flex-1 overflow-y-auto">
                <div className="flex min-w-0 flex-col gap-4">
                    {subscription.created_by ? (
                        <UserActivityIndicator
                            at={subscription.created_at}
                            by={subscription.created_by}
                            prefix="Created"
                        />
                    ) : null}
                    {siteUrlMisconfigured ? (
                        <LemonBanner type="warning">
                            Your <code>SITE_URL</code> does not match this page, so subscription links may be incorrect.{' '}
                            <Link
                                to="https://posthog.com/docs/configuring-posthog/environment-variables"
                                target="_blank"
                                targetBlankIcon
                            >
                                Configure SITE_URL
                            </Link>
                        </LemonBanner>
                    ) : null}

                    {redesignedEditorEnabled && isEditing ? (
                        <LemonTabs
                            activeKey={activeEditTab}
                            onChange={setSubscriptionEditTab}
                            className="min-w-0"
                            data-attr="subscription-edit-tabs"
                            tabs={editTabs.map((tab) => ({
                                key: tab.key,
                                label: tab.label,
                                content: contentByTab[tab.key],
                            }))}
                        />
                    ) : (
                        <div className="flex min-w-0 flex-col gap-5">
                            {reportSection}
                            {showActions ? (
                                <ProactiveSubscriptionFields logicProps={logicProps} subscription={subscription} />
                            ) : null}
                            <SubscriptionNotifySection logicProps={logicProps} subscription={subscription} />
                            <SubscriptionScheduleSection logicProps={logicProps} />
                            {deliveryStatus}
                            <SubscriptionSettingsSection
                                logicProps={logicProps}
                                subscription={subscription}
                                showEnabled={isEditing}
                            />
                            {previewSection}
                        </div>
                    )}
                </div>
            </LemonModal.Content>

            <LemonModal.Footer>
                <div className="flex-1">
                    {isEditing ? (
                        <LemonButton
                            type="secondary"
                            status="danger"
                            htmlType="button"
                            onClick={deleteCurrentSubscription}
                            disabled={subscriptionLoading || isSubscriptionSubmitting}
                        >
                            Delete subscription
                        </LemonButton>
                    ) : null}
                </div>
                <LemonButton type="secondary" htmlType="button" onClick={onCancel} disabled={isSubscriptionSubmitting}>
                    Cancel
                </LemonButton>
                <LemonButton
                    type="primary"
                    htmlType="submit"
                    loading={isSubscriptionSubmitting}
                    disabled={
                        isSubscriptionSubmitting || !subscriptionChanged || subscriptionLoading || aiGate.submitBlocked
                    }
                >
                    {isEditing ? 'Save' : 'Create subscription'}
                </LemonButton>
            </LemonModal.Footer>
        </Form>
    )
}
