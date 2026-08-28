import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { useState } from 'react'

import { IconChevronLeft, IconGraph } from '@posthog/icons'
import { LemonInput, LemonTextArea, Link } from '@posthog/lemon-ui'

import { IntegrationChoice } from 'lib/components/CyclotronJob/integrations/IntegrationChoice'
import { UsageLimitPaywall } from 'lib/components/PayGateMini/UsageLimitPaywall'
import { NextScheduledRun, ProjectTimezoneNotice } from 'lib/components/ScheduledRunStatus'
import { TZLabel } from 'lib/components/TZLabel'
import { usersLemonSelectOptions } from 'lib/components/UserSelectItem'
import { WizardReview } from 'lib/components/WizardReview'
import { dayjs } from 'lib/dayjs'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { SlackChannelPicker, SlackNotConfiguredBanner } from 'lib/integrations/SlackIntegrationHelpers'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInputSelect } from 'lib/lemon-ui/LemonInputSelect/LemonInputSelect'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel/LemonLabel'
import { LemonSelect } from 'lib/lemon-ui/LemonSelect'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { LemonSwitch } from 'lib/lemon-ui/LemonSwitch'
import { preflightLogic } from 'lib/logic/preflightLogic'
import { cn } from 'lib/utils/css-classes'
import { maxGlobalLogic } from 'scenes/max/maxGlobalLogic'
import { membersLogic } from 'scenes/organization/membersLogic'
import { organizationLogic } from 'scenes/organizationLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { DashboardType, InsightShortId, SubscriptionResourceTypes, SubscriptionType } from '~/types'

import { AiPromptFields, AiPromptSubscriptionIntroduction } from './AiPromptFields'
import { InsightSelector } from './InsightSelector'
import { SubscriptionDayPicker } from './SubscriptionDayPicker'
import { subscriptionLogic } from './subscriptionLogic'
import type { SubscriptionLogicProps } from './subscriptionLogic'
import {
    frequencyOptionsPlural,
    frequencyOptionsSingular,
    getAiSubscriptionGate,
    intervalOptions,
    bysetposOptions,
    monthlyWeekdayOptions,
    getSubscriptionAdvancedSettings,
    getNextDeliveryDate,
    formatSubscriptionSchedule,
    shouldShowDayPicker,
    requestSubscriptionWizardCancellation,
    targetTypeOptions,
    timeOptions,
    WEEKDAYS,
    weekdayOptions,
} from './utils'
import { SubscriptionCreationGate, SubscriptionFormSkeleton } from './views/EditSubscription'

interface SubscriptionWizardProps {
    insightShortId?: InsightShortId
    insightName?: string
    dashboard?: DashboardType<any> | null
    onCancel: () => void
}

enum SubscriptionWizardStep {
    Content = 'content',
    Delivery = 'delivery',
    Schedule = 'schedule',
    Review = 'review',
}

const steps = [
    { key: SubscriptionWizardStep.Content, label: 'What to send' },
    { key: SubscriptionWizardStep.Delivery, label: 'Notify' },
    { key: SubscriptionWizardStep.Schedule, label: 'Schedule' },
    { key: SubscriptionWizardStep.Review, label: 'Review' },
]

function wizardStepDescription(step: SubscriptionWizardStep): string {
    if (step === SubscriptionWizardStep.Content) {
        return 'Choose the report content to include.'
    }
    if (step === SubscriptionWizardStep.Delivery) {
        return 'Choose who to notify about this subscription.'
    }
    if (step === SubscriptionWizardStep.Schedule) {
        return 'Choose when to send this subscription.'
    }
    return 'Check the delivery details before creating the subscription.'
}

export function SubscriptionWizard({
    insightShortId,
    insightName,
    dashboard,
    onCancel,
}: SubscriptionWizardProps): JSX.Element {
    const logicProps = {
        id: 'new' as const,
        insightShortId,
        dashboardId: dashboard?.id,
        dashboardName: dashboard?.name,
        insightName,
        creationSource: 'wizard' as const,
    }
    const subscriptionFormLogic = subscriptionLogic(logicProps)
    const [currentStep, setStep] = useState<SubscriptionWizardStep>(SubscriptionWizardStep.Content)
    const {
        subscription,
        subscriptionLoading,
        subscriptionInitialized,
        isSubscriptionSubmitting,
        subscriptionChanged,
    } = useValues(subscriptionFormLogic)
    const { generatePreview, resetSubscription } = useActions(subscriptionFormLogic)
    const { preflight } = useValues(preflightLogic)
    const { currentOrganization } = useValues(organizationLogic)
    const aiSubscriptionsEnabled = useFeatureFlag('SUBSCRIPTION_AI_PROMPT')

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
    const selectedInsightsReady = !dashboard || Boolean(subscription.dashboard_export_insights?.length)
    const contentDetailReady = isAiPrompt ? Boolean(subscription.prompt?.trim()) : selectedInsightsReady
    const contentReady = Boolean(subscription.title?.trim()) && contentDetailReady
    let contentDisabledReason: string | undefined

    if (!subscription.title?.trim()) {
        contentDisabledReason = 'Enter a subscription name'
    } else if (isAiPrompt && !subscription.prompt?.trim()) {
        contentDisabledReason = 'Enter a prompt'
    } else if (aiGate.submitBlocked) {
        contentDisabledReason = 'Enable AI data processing to create an AI prompt subscription'
    } else if (!selectedInsightsReady) {
        contentDisabledReason = 'Select at least one insight'
    }
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
    let destinationDisabledReason: string | undefined
    if (!destinationReady) {
        destinationDisabledReason = emailAvailable
            ? 'Choose a destination and recipient'
            : 'Email delivery is not configured for this PostHog instance'
    }
    const currentStepIndex = steps.findIndex((step) => step.key === currentStep)
    const goToStep = (step: SubscriptionWizardStep): void => {
        if (step === SubscriptionWizardStep.Review && insightShortId && !isAiPrompt) {
            generatePreview()
        }
        setStep(step)
    }
    const requestCancel = (): void =>
        requestSubscriptionWizardCancellation({ onCancel, resetSubscription, subscriptionChanged })
    let stepContent: JSX.Element
    switch (currentStep) {
        case SubscriptionWizardStep.Content:
            stepContent = (
                <SubscriptionContentStep
                    logicProps={logicProps}
                    dashboard={dashboard}
                    insightName={insightName}
                    subscription={subscription}
                    aiSubscriptionBlocked={aiGate.submitBlocked}
                />
            )
            break
        case SubscriptionWizardStep.Delivery:
            stepContent = <SubscriptionDeliveryStep subscription={subscription} logicProps={logicProps} />
            break
        case SubscriptionWizardStep.Schedule:
            stepContent = <SubscriptionScheduleStep logicProps={logicProps} />
            break
        case SubscriptionWizardStep.Review:
            stepContent = (
                <SubscriptionReviewStep
                    logicProps={logicProps}
                    subscription={subscription}
                    dashboard={dashboard}
                    insightShortId={insightShortId}
                />
            )
            break
        default:
            stepContent = <></>
    }
    const nextStep = steps[currentStepIndex + 1]?.key
    let continueDisabledReason: string | undefined
    if (currentStep === SubscriptionWizardStep.Content) {
        continueDisabledReason = contentReady ? undefined : contentDisabledReason
    } else if (currentStep === SubscriptionWizardStep.Delivery) {
        continueDisabledReason = destinationDisabledReason
    } else if (currentStep === SubscriptionWizardStep.Schedule) {
        continueDisabledReason = scheduleReady ? undefined : 'Choose a delivery time and at least one delivery day'
    }
    let primaryAction: JSX.Element | null = null
    if (currentStep === SubscriptionWizardStep.Review) {
        primaryAction = (
            <LemonButton type="primary" htmlType="submit" loading={isSubscriptionSubmitting}>
                Create subscription
            </LemonButton>
        )
    } else if (nextStep) {
        primaryAction = (
            <LemonButton
                type="primary"
                htmlType="button"
                onClick={(event) => {
                    event.preventDefault()
                    goToStep(nextStep)
                }}
                disabledReason={continueDisabledReason}
            >
                Continue
            </LemonButton>
        )
    }

    return (
        <SubscriptionCreationGate onCancel={requestCancel}>
            <Form
                logic={subscriptionLogic}
                props={logicProps}
                formKey="subscription"
                enableFormOnSubmit
                className="flex flex-1 flex-col min-h-0"
            >
                <div className="flex min-h-[36rem] flex-1 flex-col overflow-hidden">
                    <header className="border-b p-4">
                        <div className="flex items-center gap-2">
                            <LemonButton
                                type="tertiary"
                                size="small"
                                icon={<IconChevronLeft />}
                                onClick={requestCancel}
                            />
                            <h2 className="text-lg font-semibold m-0">New subscription</h2>
                        </div>
                        <nav aria-label="Subscription setup progress" className="mt-3">
                            <ol className="flex flex-wrap items-center gap-x-1 gap-y-2">
                                {steps.map((step, index) => {
                                    const isCurrent = index === currentStepIndex
                                    const isComplete = index < currentStepIndex
                                    const canAccess = index <= currentStepIndex
                                    return (
                                        <li key={step.key} className="flex shrink-0 items-center gap-1">
                                            <button
                                                type="button"
                                                disabled={!canAccess}
                                                onClick={() => canAccess && goToStep(step.key)}
                                                className={cn(
                                                    'flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-accent',
                                                    canAccess && 'cursor-pointer',
                                                    !canAccess && 'opacity-40 cursor-not-allowed',
                                                    isCurrent
                                                        ? 'bg-accent text-white font-semibold'
                                                        : isComplete
                                                          ? 'bg-success-highlight text-success'
                                                          : 'text-muted hover:bg-border'
                                                )}
                                                aria-current={isCurrent ? 'step' : undefined}
                                            >
                                                <span
                                                    className={cn(
                                                        'inline-flex size-5 shrink-0 items-center justify-center rounded-full text-[11px] font-bold',
                                                        isCurrent
                                                            ? 'bg-white text-accent'
                                                            : isComplete
                                                              ? 'bg-success text-white'
                                                              : 'border border-border'
                                                    )}
                                                >
                                                    {index + 1}
                                                </span>
                                                <span>{step.label}</span>
                                            </button>
                                            {index < steps.length - 1 ? <span className="text-border">→</span> : null}
                                        </li>
                                    )
                                })}
                            </ol>
                        </nav>
                    </header>
                    <section className="p-4 min-h-0 flex-1 overflow-y-auto">
                        <div className="space-y-1 mb-3">
                            <h3 className="text-base font-semibold m-0">{steps[currentStepIndex].label}</h3>
                            <p className="text-xs text-secondary m-0">{wizardStepDescription(currentStep)}</p>
                        </div>
                        {stepContent}
                    </section>
                    <footer className="flex flex-wrap items-center justify-between gap-2 border-t p-4">
                        <div />
                        <div className="flex items-center gap-2">
                            {currentStep === SubscriptionWizardStep.Content ? (
                                <LemonButton type="secondary" htmlType="button" onClick={requestCancel}>
                                    Close
                                </LemonButton>
                            ) : (
                                <LemonButton
                                    type="secondary"
                                    htmlType="button"
                                    icon={<IconChevronLeft className="size-4" />}
                                    onClick={() => setStep(steps[currentStepIndex - 1].key)}
                                    disabled={isSubscriptionSubmitting}
                                >
                                    Back
                                </LemonButton>
                            )}
                            {primaryAction}
                        </div>
                    </footer>
                </div>
            </Form>
        </SubscriptionCreationGate>
    )
}

function SubscriptionDeliveryStep({
    subscription,
    logicProps,
}: {
    subscription: SubscriptionType
    logicProps: SubscriptionLogicProps
}): JSX.Element {
    const { meFirstMembers, membersLoading } = useValues(membersLogic)
    const { integrations, slackIntegrations } = useValues(integrationsLogic)
    const { preflight } = useValues(preflightLogic)
    const { setSubscriptionValue } = useActions(subscriptionLogic(logicProps))

    return (
        <div className="flex flex-col gap-4">
            <LemonField name="target_type" label="Send to">
                <LemonSelect options={targetTypeOptions} />
            </LemonField>
            {subscription.target_type === 'email' && !preflight?.email_service_available ? (
                <LemonBanner type="error">
                    Email subscriptions are not available because this PostHog instance is not configured to send email.{' '}
                    <Link to="https://posthog.com/docs/self-host/configure/email" target="_blank" targetBlankIcon>
                        Configure email delivery
                    </Link>
                </LemonBanner>
            ) : null}
            {subscription.target_type === 'email' ? (
                <>
                    <LemonField name="target_value" label="Recipients">
                        {({ value, onChange }) => (
                            <LemonInputSelect
                                value={value?.split(',').filter(Boolean)}
                                onChange={(recipients) => onChange(recipients.join(','))}
                                mode="multiple"
                                allowCustomValues
                                options={usersLemonSelectOptions(meFirstMembers.map((member) => member.user))}
                                loading={membersLoading}
                                placeholder="Enter an email address"
                            />
                        )}
                    </LemonField>
                    <LemonField name="invite_message" label="Message" showOptional>
                        <LemonTextArea placeholder="Message for recipients" />
                    </LemonField>
                </>
            ) : null}
            {subscription.target_type === 'slack' ? (
                !slackIntegrations?.length ? (
                    <SlackNotConfiguredBanner />
                ) : (
                    <>
                        <LemonField name="integration_id" label="Slack connection">
                            {({ value, onChange }) => (
                                <IntegrationChoice
                                    integration="slack"
                                    value={value}
                                    onChange={(integrationId) => {
                                        onChange(integrationId)
                                        if (value !== null && integrationId !== value) {
                                            setSubscriptionValue('target_value', '')
                                        }
                                    }}
                                />
                            )}
                        </LemonField>
                        {subscription.integration_id ? (
                            <LemonField name="target_value" label="Slack channel">
                                {({ value, onChange }) => {
                                    const integration = integrations?.find(
                                        (item) => item.id === subscription.integration_id
                                    )
                                    return integration ? (
                                        <SlackChannelPicker
                                            value={value}
                                            onChange={onChange}
                                            integration={integration}
                                        />
                                    ) : (
                                        <></>
                                    )
                                }}
                            </LemonField>
                        ) : null}
                    </>
                )
            ) : null}
        </div>
    )
}

function SubscriptionContentStep({
    logicProps,
    dashboard,
    insightName,
    subscription,
    aiSubscriptionBlocked,
}: {
    logicProps: SubscriptionLogicProps
    dashboard?: DashboardType<any> | null
    insightName?: string
    subscription: SubscriptionType
    aiSubscriptionBlocked: boolean
}): JSX.Element {
    const { applyDefaultSelectedInsights, selectAiAnalysisWindow, selectAiExamplePrompt } = useActions(
        subscriptionLogic(logicProps)
    )
    const isAiPrompt = subscription.resource_type === SubscriptionResourceTypes.AiPrompt

    return (
        <div className="flex flex-col gap-4">
            {isAiPrompt ? <AiPromptSubscriptionIntroduction /> : null}
            {isAiPrompt && aiSubscriptionBlocked ? (
                <LemonBanner type="info">
                    Enable AI data processing in your Organization settings to create an AI prompt subscription.{' '}
                    <Link to={urls.settings('organization-details', 'organization-ai-consent')}>
                        Manage AI data processing
                    </Link>
                </LemonBanner>
            ) : null}
            {insightName && !isAiPrompt ? (
                <div className="flex items-center gap-2 font-semibold">
                    <IconGraph className="size-5 shrink-0 text-accent" />
                    {insightName}
                </div>
            ) : null}
            <LemonField name="title" label="Name">
                <LemonInput />
            </LemonField>
            {isAiPrompt ? (
                <AiPromptFields
                    compactAnalysisWindow
                    prompt={subscription.prompt}
                    windowMode={subscription.ai_prompt_config?.window?.mode}
                    onSelectAnalysisWindow={selectAiAnalysisWindow}
                    onSelectExample={selectAiExamplePrompt}
                />
            ) : null}
            {dashboard?.tiles && !isAiPrompt ? (
                <LemonField name="dashboard_export_insights" label="Insights to include">
                    {({ value, onChange }) => (
                        <InsightSelector
                            tiles={dashboard.tiles}
                            selectedInsightIds={value ?? []}
                            onChange={onChange}
                            onDefaultsApplied={applyDefaultSelectedInsights}
                        />
                    )}
                </LemonField>
            ) : null}
            <SubscriptionSettingsStep subscription={subscription} logicProps={logicProps} />
        </div>
    )
}

function SubscriptionScheduleStep({ logicProps }: { logicProps: SubscriptionLogicProps }): JSX.Element {
    const { subscription } = useValues(subscriptionLogic(logicProps))
    const { currentTeam } = useValues(teamLogic)
    const availableFrequencyOptions = subscription?.interval === 1 ? frequencyOptionsSingular : frequencyOptionsPlural
    const nextDeliveryDate = subscription ? getNextDeliveryDate(subscription) : null

    return (
        <div className="flex flex-col gap-4">
            <LemonLabel>When should we send it?</LemonLabel>
            <div className="flex flex-wrap items-center gap-2">
                <span>Every</span>
                <LemonField name="interval">
                    <LemonSelect options={intervalOptions} />
                </LemonField>
                <LemonField name="frequency">
                    <LemonSelect options={availableFrequencyOptions} />
                </LemonField>
                {subscription && shouldShowDayPicker(subscription.frequency, subscription.interval) ? (
                    <>
                        <span>on</span>
                        <LemonField name="byweekday">
                            {({ value, onChange }) => <SubscriptionDayPicker value={value ?? []} onChange={onChange} />}
                        </LemonField>
                    </>
                ) : null}
                {subscription?.frequency === 'monthly' ? (
                    <>
                        <span>on the</span>
                        <LemonField name="bysetpos">
                            {({ value, onChange }) => (
                                <LemonSelect
                                    options={bysetposOptions}
                                    value={value ? String(value) : null}
                                    onChange={(value) => onChange(value === null ? null : Number(value))}
                                />
                            )}
                        </LemonField>
                        <LemonField name="byweekday">
                            {({ value, onChange }) => {
                                const isWeekday = value?.length === 5 && value.every((day: string) => WEEKDAYS.has(day))
                                let displayValue = 'day'
                                if (isWeekday) {
                                    displayValue = 'weekday'
                                } else if (value?.length === 1) {
                                    displayValue = value[0]
                                }

                                return (
                                    <LemonSelect
                                        dropdownMatchSelectWidth={false}
                                        options={monthlyWeekdayOptions}
                                        value={displayValue}
                                        onChange={(value) => {
                                            if (value === 'day') {
                                                onChange(weekdayOptions.map(({ value }) => value))
                                                return
                                            }
                                            if (value === 'weekday') {
                                                onChange([...WEEKDAYS])
                                                return
                                            }
                                            onChange([value])
                                        }}
                                    />
                                )
                            }}
                        </LemonField>
                    </>
                ) : null}
                <span>at</span>
                <LemonField name="start_date">
                    {({ value, onChange }) => (
                        <LemonSelect
                            options={timeOptions}
                            value={dayjs(value).hour().toString()}
                            onChange={(hour) =>
                                onChange(
                                    dayjs()
                                        .hour(Number(hour ?? 0))
                                        .minute(0)
                                        .second(0)
                                        .toISOString()
                                )
                            }
                        />
                    )}
                </LemonField>
            </div>
            {nextDeliveryDate ? (
                <div className="flex flex-col gap-3">
                    <NextScheduledRun label="Next planned delivery:">
                        <span>
                            Approximately <TZLabel time={dayjs(nextDeliveryDate)} />
                        </span>
                    </NextScheduledRun>
                    <ProjectTimezoneNotice
                        timezone={currentTeam?.timezone ?? 'UTC'}
                        settingsUrl={urls.settings('environment-customization', 'date-and-time')}
                    />
                </div>
            ) : null}
        </div>
    )
}

function SubscriptionSettingsStep({
    subscription,
    logicProps,
}: {
    subscription: SubscriptionType
    logicProps: SubscriptionLogicProps
}): JSX.Element {
    const { dataProcessingAccepted } = useValues(maxGlobalLogic)
    const { summaryQuota } = useValues(subscriptionLogic(logicProps))

    return (
        <div className="mt-6 flex flex-col gap-2">
            <LemonLabel>Advanced settings</LemonLabel>
            {dataProcessingAccepted && subscription.resource_type !== SubscriptionResourceTypes.AiPrompt ? (
                <LemonField name="summary_enabled">
                    {({ value, onChange }) => (
                        <LemonSwitch
                            checked={value}
                            onChange={onChange}
                            disabledReason={
                                summaryQuota?.at_limit && !value
                                    ? `Plan limit reached (${summaryQuota.limit} active AI summaries)`
                                    : undefined
                            }
                            bordered
                            fullWidth
                            label={
                                <div className="flex flex-col gap-1 py-1">
                                    <div className="leading-tight">Include an automatic AI summary</div>
                                    <div className="text-xs text-secondary font-normal leading-tight">
                                        Add an AI-written overview of the report to each delivery.
                                    </div>
                                </div>
                            }
                        />
                    )}
                </LemonField>
            ) : null}
            {summaryQuota?.at_limit && !subscription.summary_enabled && summaryQuota.limit !== null ? (
                <UsageLimitPaywall
                    title="AI summary limit reached"
                    description="Disable an existing AI summary or upgrade your plan to add more."
                    limit={summaryQuota.limit}
                    currentUsage={summaryQuota.active_count}
                    unit="active AI summaries on your plan"
                />
            ) : null}
            <LemonField name="send_test_now">
                {({ value, onChange }) => (
                    <LemonSwitch
                        checked={value}
                        onChange={onChange}
                        bordered
                        fullWidth
                        label={
                            <div className="flex flex-col gap-1 py-1">
                                <div className="leading-tight">Send a test run now</div>
                                <div className="text-xs text-secondary font-normal leading-tight">
                                    Send this report once now so you can confirm the delivery.
                                </div>
                            </div>
                        }
                    />
                )}
            </LemonField>
        </div>
    )
}

function formatAiAnalysisWindow(subscription: SubscriptionType): string {
    const window = subscription.ai_prompt_config?.window

    if (window?.mode === 'last_n_days') {
        return `Last ${window.start_days_ago} days`
    }
    if (window?.mode === 'days_ago_range') {
        return `${window.start_days_ago} to ${window.end_days_ago} days ago`
    }
    return 'Since last report'
}

function SubscriptionReviewStep({
    logicProps,
    subscription,
    dashboard,
    insightShortId,
}: {
    logicProps: SubscriptionLogicProps
    subscription: SubscriptionType
    dashboard?: DashboardType<any> | null
    insightShortId?: InsightShortId
}): JSX.Element {
    const { previewLoading, previewError, previewImageUrl } = useValues(subscriptionLogic(logicProps))
    const { generatePreview } = useActions(subscriptionLogic(logicProps))
    const selectedInsightsCount = subscription.dashboard_export_insights?.length ?? 0
    const advancedSettings = getSubscriptionAdvancedSettings(subscription)
    const nextDeliveryDate = getNextDeliveryDate(subscription)
    const isAiPrompt = subscription.resource_type === SubscriptionResourceTypes.AiPrompt
    let reviewNotice: JSX.Element

    if (subscription.send_test_now) {
        reviewNotice = <>We will send a test report now so you can confirm the delivery.</>
    } else if (nextDeliveryDate) {
        reviewNotice = (
            <>
                No test report will be sent. The first scheduled report will arrive{' '}
                <TZLabel
                    time={dayjs(nextDeliveryDate)}
                    formatDate="ddd, MMM D"
                    formatTime="h:mm A"
                    timestampStyle="absolute"
                />
                .
            </>
        )
    } else {
        reviewNotice = <>No test report will be sent. The subscription will start on its normal schedule.</>
    }
    const reviewItems = [
        { label: 'Name', value: subscription.title },
        ...(isAiPrompt
            ? [
                  { label: 'Prompt', value: subscription.prompt ?? '' },
                  { label: 'Analysis window', value: formatAiAnalysisWindow(subscription) },
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
        ...(advancedSettings.length ? [{ label: 'Advanced settings', value: advancedSettings.join(' · ') }] : []),
    ]

    return (
        <div className="flex flex-col gap-4">
            <WizardReview items={reviewItems} footer={<div className="text-secondary text-sm">{reviewNotice}</div>} />
            {insightShortId && !isAiPrompt ? (
                <div>
                    <LemonLabel className="mb-2">Preview</LemonLabel>
                    <div className="border rounded p-2">
                        {previewLoading ? (
                            <div className="overflow-hidden rounded border">
                                <LemonSkeleton className="aspect-video w-full" />
                            </div>
                        ) : null}
                        {previewError ? (
                            <div className="flex flex-col items-start gap-2">
                                <LemonBanner type="error">{previewError}</LemonBanner>
                                <LemonButton
                                    type="secondary"
                                    htmlType="button"
                                    onClick={generatePreview}
                                    disabled={previewLoading}
                                    size="small"
                                    data-attr="subscription-wizard-generate-preview"
                                >
                                    Try again
                                </LemonButton>
                            </div>
                        ) : null}
                        {previewImageUrl ? (
                            <div className="mt-2 border rounded">
                                <img src={previewImageUrl} alt="Subscription export preview" className="w-full" />
                            </div>
                        ) : null}
                    </div>
                </div>
            ) : null}
        </div>
    )
}
