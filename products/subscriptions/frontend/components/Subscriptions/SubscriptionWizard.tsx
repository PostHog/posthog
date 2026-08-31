import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { IconChevronLeft } from '@posthog/icons'
import { Link } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { WizardReview } from 'lib/components/WizardReview'
import { dayjs } from 'lib/dayjs'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel/LemonLabel'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { preflightLogic } from 'lib/logic/preflightLogic'
import { organizationLogic } from 'scenes/organizationLogic'
import { urls } from 'scenes/urls'

import { DashboardType, InsightShortId, SubscriptionResourceTypes } from '~/types'

import { ProactiveSubscriptionFields } from './ProactiveSubscriptionFields'
import {
    getSubscriptionWizardSteps,
    normalizeSubscriptionWizardStep,
    shouldShowSubscriptionActions,
    shouldWaitForSubscriptionActions,
} from './subscriptionFormNavigation'
import type { SubscriptionWizardStep } from './subscriptionFormNavigation'
import { subscriptionLogic } from './subscriptionLogic'
import type { SubscriptionFormType, SubscriptionLogicProps } from './subscriptionLogic'
import { SubscriptionNotifySection } from './SubscriptionNotifySection'
import { SubscriptionReportSection } from './SubscriptionReportSection'
import { SubscriptionScheduleSection } from './SubscriptionScheduleSection'
import { SubscriptionSettingsSection } from './SubscriptionSettingsSection'
import {
    formatSubscriptionSchedule,
    getAiSubscriptionGate,
    getNextDeliveryDate,
    getSubscriptionAdvancedSettings,
    requestSubscriptionWizardCancellation,
    shouldShowDayPicker,
} from './utils'
import { SubscriptionCreationGate, SubscriptionFormSkeleton } from './views/EditSubscription'

interface SubscriptionWizardProps {
    insightShortId?: InsightShortId
    insightName?: string
    dashboard?: DashboardType<any> | null
    onCancel: () => void
}

export function SubscriptionWizard({
    insightShortId,
    insightName,
    dashboard,
    onCancel,
}: SubscriptionWizardProps): JSX.Element {
    const logicProps: SubscriptionLogicProps = {
        id: 'new',
        insightShortId,
        dashboardId: dashboard?.id,
        dashboardName: dashboard?.name,
        insightName,
        creationSource: 'wizard',
    }
    const logic = subscriptionLogic(logicProps)
    const {
        subscription,
        subscriptionLoading,
        subscriptionInitialized,
        isSubscriptionSubmitting,
        subscriptionChanged,
        subscriptionWizardStep,
        proactiveConfigurationOptions,
        proactiveConfigurationOptionsLoading,
        proactiveConfigurationOptionsLoadFailed,
    } = useValues(logic)
    const { generatePreview, resetSubscription, setSubscriptionWizardStep } = useActions(logic)
    const { preflight } = useValues(preflightLogic)
    const { currentOrganization } = useValues(organizationLogic)
    const aiSubscriptionsEnabled = useFeatureFlag('SUBSCRIPTION_AI_PROMPT')
    const aiContextsEnabled = useFeatureFlag('SUBSCRIPTION_AI_CONTEXTS')

    if (subscriptionLoading || !subscriptionInitialized) {
        return <SubscriptionFormSkeleton />
    }
    if (!subscription) {
        return <div>Could not load the subscription form.</div>
    }

    const isAiPrompt = subscription.resource_type === SubscriptionResourceTypes.AiPrompt
    const aiGate = getAiSubscriptionGate({
        isAiPrompt,
        isParentless: !insightShortId && !dashboard,
        isEditing: false,
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
    if (shouldWaitForSubscriptionActions(actionsVisibility)) {
        return <SubscriptionFormSkeleton />
    }

    const showActions = shouldShowSubscriptionActions(actionsVisibility)
    const steps = getSubscriptionWizardSteps(showActions)
    const currentStep = normalizeSubscriptionWizardStep(subscriptionWizardStep, showActions)
    const currentStepIndex = steps.findIndex(({ key }) => key === currentStep)
    const selectedInsightsReady = !dashboard || Boolean(subscription.dashboard_export_insights?.length)
    const contentDetailReady = isAiPrompt ? Boolean(subscription.prompt?.trim()) : selectedInsightsReady
    const contentReady = Boolean(subscription.title?.trim()) && contentDetailReady && !aiGate.submitBlocked
    const emailAvailable = subscription.target_type !== 'email' || Boolean(preflight?.email_service_available)
    const destinationReady = Boolean(
        emailAvailable &&
        subscription.target_value &&
        (subscription.target_type !== 'slack' || subscription.integration_id)
    )
    const requiresDeliveryDays = shouldShowDayPicker(subscription.frequency, subscription.interval)
    const scheduleReady = Boolean(
        subscription.frequency &&
        subscription.interval &&
        subscription.start_date &&
        (!requiresDeliveryDays || subscription.byweekday?.length)
    )

    const goToStep = (step: SubscriptionWizardStep): void => {
        if (step === 'review' && insightShortId && !isAiPrompt) {
            generatePreview()
        }
        setSubscriptionWizardStep(step)
    }
    const requestCancel = (): void =>
        requestSubscriptionWizardCancellation({ onCancel, resetSubscription, subscriptionChanged })

    let continueDisabledReason: string | undefined
    if (currentStep === 'report') {
        if (!subscription.title?.trim()) {
            continueDisabledReason = 'Enter a subscription name'
        } else if (isAiPrompt && !subscription.prompt?.trim()) {
            continueDisabledReason = 'Enter a prompt'
        } else if (aiGate.submitBlocked) {
            continueDisabledReason = 'Enable AI data processing to create an AI report'
        } else if (!selectedInsightsReady) {
            continueDisabledReason = 'Select at least one insight'
        }
    } else if (currentStep === 'actions') {
        if (
            subscription.proactive_config?.enabled &&
            subscription.proactive_config.create_draft_pr &&
            (!subscription.proactive_config.repository || !subscription.proactive_config.repository_integration_id)
        ) {
            continueDisabledReason = 'Select a repository for draft pull requests'
        }
    } else if (currentStep === 'notify' && !destinationReady) {
        continueDisabledReason = emailAvailable
            ? 'Choose a destination and recipient'
            : 'Email delivery is not configured for this PostHog instance'
    } else if (currentStep === 'schedule' && !scheduleReady) {
        continueDisabledReason = 'Choose a delivery time and at least one delivery day'
    }

    let stepContent: JSX.Element
    if (currentStep === 'report') {
        stepContent = (
            <SubscriptionReportSection
                logicProps={logicProps}
                dashboard={dashboard}
                insightName={insightName}
                subscription={subscription}
                aiContextsEnabled={Boolean(aiContextsEnabled)}
                compactAnalysisWindow
                aiConsentMessage={
                    aiGate.submitBlocked ? (
                        <>
                            Enable AI data processing to create an AI report.{' '}
                            <Link to={urls.settings('organization-details', 'organization-ai-consent')}>
                                Manage AI data processing
                            </Link>
                        </>
                    ) : undefined
                }
            />
        )
    } else if (currentStep === 'actions') {
        stepContent = <ProactiveSubscriptionFields logicProps={logicProps} subscription={subscription} />
    } else if (currentStep === 'notify') {
        stepContent = <SubscriptionNotifySection logicProps={logicProps} subscription={subscription} />
    } else if (currentStep === 'schedule') {
        stepContent = <SubscriptionScheduleSection logicProps={logicProps} />
    } else {
        stepContent = (
            <div className="flex flex-col gap-5">
                <SubscriptionReviewStep
                    logicProps={logicProps}
                    subscription={subscription}
                    dashboard={dashboard}
                    insightShortId={insightShortId}
                />
                <SubscriptionSettingsSection logicProps={logicProps} subscription={subscription} />
            </div>
        )
    }

    const nextStep = steps[currentStepIndex + 1]?.key
    const primaryAction =
        currentStep === 'review' ? (
            <LemonButton
                type="primary"
                htmlType="submit"
                loading={isSubscriptionSubmitting}
                disabled={isSubscriptionSubmitting || !contentReady || !destinationReady || !scheduleReady}
            >
                Create subscription
            </LemonButton>
        ) : nextStep ? (
            <LemonButton
                type="primary"
                htmlType="button"
                onClick={(event) => {
                    event.preventDefault()
                    goToStep(nextStep)
                }}
                disabledReason={continueDisabledReason}
                disabled={isSubscriptionSubmitting}
            >
                Continue
            </LemonButton>
        ) : null

    return (
        <SubscriptionCreationGate onCancel={requestCancel}>
            <Form
                logic={subscriptionLogic}
                props={logicProps}
                formKey="subscription"
                enableFormOnSubmit
                className="flex min-h-0 flex-1 flex-col"
            >
                <div className="flex min-h-[36rem] min-w-0 flex-1 flex-col overflow-hidden">
                    <header className="border-b p-4">
                        <div className="flex items-center gap-2">
                            <LemonButton
                                type="tertiary"
                                size="small"
                                icon={<IconChevronLeft />}
                                onClick={requestCancel}
                            />
                            <h2 className="m-0 text-lg font-semibold">New subscription</h2>
                        </div>
                        <LemonTabs
                            activeKey={currentStep}
                            onChange={goToStep}
                            size="small"
                            className="mt-3 min-w-0"
                            data-attr="subscription-wizard-steps"
                            tabs={steps.map((step, index) => ({
                                key: step.key,
                                label: `${index + 1}. ${step.label}`,
                                completed: index < currentStepIndex,
                                disabledReason:
                                    index > currentStepIndex
                                        ? 'Complete the current step before continuing'
                                        : undefined,
                            }))}
                        />
                    </header>
                    <section className="min-h-0 min-w-0 flex-1 overflow-y-auto p-4">
                        <div className="mb-3 space-y-1">
                            <h3 className="m-0 text-base font-semibold">{steps[currentStepIndex].label}</h3>
                            <p className="m-0 text-xs text-secondary">{steps[currentStepIndex].description}</p>
                        </div>
                        {stepContent}
                    </section>
                    <footer className="flex flex-wrap items-center justify-end gap-2 border-t p-4">
                        {currentStep === 'report' ? (
                            <LemonButton type="secondary" htmlType="button" onClick={requestCancel}>
                                Close
                            </LemonButton>
                        ) : (
                            <LemonButton
                                type="secondary"
                                htmlType="button"
                                icon={<IconChevronLeft className="size-4" />}
                                onClick={() => setSubscriptionWizardStep(steps[currentStepIndex - 1].key)}
                                disabled={isSubscriptionSubmitting}
                            >
                                Back
                            </LemonButton>
                        )}
                        {primaryAction}
                    </footer>
                </div>
            </Form>
        </SubscriptionCreationGate>
    )
}

function formatAiAnalysisWindow(subscription: SubscriptionFormType): string {
    const window = subscription.ai_prompt_config?.window
    if (window?.mode === 'last_n_days') {
        return `Last ${window.start_days_ago} days`
    }
    if (window?.mode === 'days_ago_range') {
        return `${window.start_days_ago} to ${window.end_days_ago} days ago`
    }
    return 'Since last report'
}

function formatProactiveActions(subscription: SubscriptionFormType): string {
    if (!subscription.proactive_config?.enabled) {
        return 'None'
    }
    return subscription.proactive_config.create_draft_pr
        ? 'Recommendations, draft pull request, and experiment draft'
        : 'Recommendations and experiment draft'
}

function SubscriptionReviewStep({
    logicProps,
    subscription,
    dashboard,
    insightShortId,
}: {
    logicProps: SubscriptionLogicProps
    subscription: SubscriptionFormType
    dashboard?: DashboardType<any> | null
    insightShortId?: InsightShortId
}): JSX.Element {
    const { previewLoading, previewError, previewImageUrl } = useValues(subscriptionLogic(logicProps))
    const { generatePreview } = useActions(subscriptionLogic(logicProps))
    const selectedInsightsCount = subscription.dashboard_export_insights?.length ?? 0
    const advancedSettings = getSubscriptionAdvancedSettings(subscription)
    const nextDeliveryDate = getNextDeliveryDate(subscription)
    const isAiPrompt = subscription.resource_type === SubscriptionResourceTypes.AiPrompt
    const reviewItems = [
        { label: 'Name', value: subscription.title },
        ...(isAiPrompt
            ? [
                  { label: 'Goal', value: subscription.prompt ?? '' },
                  { label: 'Analysis window', value: formatAiAnalysisWindow(subscription) },
                  { label: 'Actions', value: formatProactiveActions(subscription) },
              ]
            : []),
        { label: 'Sends to', value: subscription.target_value },
        { label: 'Runs', value: formatSubscriptionSchedule(subscription) },
        ...(dashboard
            ? [
                  {
                      label: 'Insights',
                      value: `${selectedInsightsCount} ${selectedInsightsCount === 1 ? 'insight' : 'insights'} included`,
                  },
              ]
            : []),
        ...(advancedSettings.length ? [{ label: 'Options', value: advancedSettings.join(' · ') }] : []),
    ]

    return (
        <div className="flex flex-col gap-4">
            <WizardReview
                items={reviewItems}
                footer={
                    <div className="text-sm text-secondary">
                        {nextDeliveryDate ? (
                            <>
                                First scheduled report:{' '}
                                <TZLabel
                                    time={dayjs(nextDeliveryDate)}
                                    formatDate="ddd, MMM D"
                                    formatTime="h:mm A"
                                    timestampStyle="absolute"
                                />
                            </>
                        ) : (
                            <>The subscription starts on its normal schedule.</>
                        )}
                    </div>
                }
            />
            {insightShortId && !isAiPrompt ? (
                <div>
                    <LemonLabel className="mb-2">Preview</LemonLabel>
                    <div className="rounded border p-2">
                        {previewLoading ? <LemonSkeleton className="aspect-video w-full" /> : null}
                        {previewError ? (
                            <div className="flex flex-col items-start gap-2">
                                <LemonBanner type="error">{previewError}</LemonBanner>
                                <LemonButton
                                    type="secondary"
                                    htmlType="button"
                                    onClick={generatePreview}
                                    disabled={previewLoading}
                                    loading={previewLoading}
                                    size="small"
                                >
                                    Try again
                                </LemonButton>
                            </div>
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
            ) : null}
        </div>
    )
}
