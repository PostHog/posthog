import { useValues } from 'kea'

import { FlaggedFeature } from 'lib/components/FlaggedFeature'
import { UsageLimitPaywall } from 'lib/components/PayGateMini/UsageLimitPaywall'
import { TZLabel } from 'lib/components/TZLabel'
import { FEATURE_FLAGS } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel/LemonLabel'
import { LemonSwitch } from 'lib/lemon-ui/LemonSwitch'
import { LemonTextArea } from 'lib/lemon-ui/LemonTextArea'
import { maxGlobalLogic } from 'scenes/max/maxGlobalLogic'
import { AIConsentPopoverWrapper } from 'scenes/settings/organization/AIConsentPopoverWrapper'

import { SubscriptionResourceTypes } from '~/types'

import { subscriptionLogic } from './subscriptionLogic'
import type { SubscriptionFormType, SubscriptionLogicProps } from './subscriptionLogic'
import { getNextDeliveryDate } from './utils'

interface SubscriptionSettingsSectionProps {
    logicProps: SubscriptionLogicProps
    subscription: SubscriptionFormType
    showEnabled?: boolean
    showSendTestNow?: boolean
}

export function SubscriptionSettingsSection({
    logicProps,
    subscription,
    showEnabled = false,
    showSendTestNow = true,
}: SubscriptionSettingsSectionProps): JSX.Element {
    const { summaryQuota } = useValues(subscriptionLogic(logicProps))
    const { dataProcessingAccepted } = useValues(maxGlobalLogic)
    const isAiPrompt = subscription.resource_type === SubscriptionResourceTypes.AiPrompt
    const nextDeliveryDate = getNextDeliveryDate(subscription)

    return (
        <div className="flex min-w-0 flex-col gap-3">
            {showEnabled ? (
                <>
                    <LemonLabel>Subscription status</LemonLabel>
                    <LemonField name="enabled">
                        {({ value, onChange }) => (
                            <LemonSwitch
                                checked={value !== false}
                                onChange={onChange}
                                bordered
                                fullWidth
                                data-attr="subscription-enabled"
                                label={
                                    <div className="flex flex-col gap-1 py-1">
                                        <div className="leading-tight">Subscription enabled</div>
                                        <div className="text-xs font-normal leading-tight text-secondary">
                                            Pause scheduled reports without deleting this subscription.
                                        </div>
                                    </div>
                                }
                            />
                        )}
                    </LemonField>
                </>
            ) : null}

            {!isAiPrompt ? (
                <>
                    <LemonLabel>AI summary</LemonLabel>
                    <LemonField name="summary_enabled">
                        {({ value, onChange }) => (
                            <AIConsentPopoverWrapper>
                                <LemonSwitch
                                    checked={value}
                                    onChange={onChange}
                                    bordered
                                    fullWidth
                                    label="Include an automatic AI summary"
                                    disabledReason={
                                        !dataProcessingAccepted && !value
                                            ? 'Your organization needs to approve AI data processing before enabling AI summaries'
                                            : summaryQuota?.at_limit && !value
                                              ? `Plan limit reached (${summaryQuota.limit} active AI summaries)`
                                              : undefined
                                    }
                                />
                            </AIConsentPopoverWrapper>
                        )}
                    </LemonField>
                    {summaryQuota?.at_limit && !subscription.summary_enabled && summaryQuota.limit !== null ? (
                        <UsageLimitPaywall
                            title="AI summary limit reached"
                            description="Disable an existing AI summary or upgrade your plan to add more."
                            limit={summaryQuota.limit}
                            currentUsage={summaryQuota.active_count}
                            unit="active AI summaries on your plan"
                        />
                    ) : null}
                    {subscription.summary_enabled ? (
                        <FlaggedFeature flag={FEATURE_FLAGS.SUBSCRIPTION_AI_SUMMARY_PROMPT_GUIDE}>
                            <LemonField name="summary_prompt_guide" label="Context for the AI summary" showOptional>
                                <LemonTextArea
                                    placeholder="e.g. Focus on revenue drop-off and churn signals"
                                    maxLength={500}
                                />
                            </LemonField>
                        </FlaggedFeature>
                    ) : null}
                </>
            ) : null}

            {showSendTestNow ? (
                <>
                    <LemonLabel>Test delivery</LemonLabel>
                    <LemonField name="send_test_now">
                        {({ value, onChange }) => (
                            <LemonSwitch
                                checked={subscription.enabled === false ? false : value}
                                onChange={onChange}
                                bordered
                                fullWidth
                                label="Send a test report when I save"
                                disabledReason={
                                    subscription.enabled === false
                                        ? 'Re-enable this subscription before sending a test report'
                                        : undefined
                                }
                            />
                        )}
                    </LemonField>
                    <p className="m-0 text-xs text-secondary">
                        {subscription.send_test_now
                            ? 'PostHog will send this report once after you save, so you can check the result.'
                            : 'No test report will be sent. The subscription will wait for its next scheduled run'}
                        {!subscription.send_test_now && nextDeliveryDate ? (
                            <>
                                {' on '}
                                <TZLabel
                                    time={dayjs(nextDeliveryDate)}
                                    formatDate="ddd, MMM D"
                                    formatTime="h:mm A"
                                    timestampStyle="absolute"
                                />
                            </>
                        ) : null}
                        {!subscription.send_test_now ? '.' : null}
                    </p>
                </>
            ) : null}
        </div>
    )
}
