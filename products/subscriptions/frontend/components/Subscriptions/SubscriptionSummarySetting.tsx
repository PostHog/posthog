import { useValues } from 'kea'
import posthog from 'posthog-js'

import { useFeatureFlagVariantKey } from '@posthog/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonSwitch } from 'lib/lemon-ui/LemonSwitch'

import { subscriptionLogic } from './subscriptionLogic'
import type { SubscriptionLogicProps } from './subscriptionLogic'

export function SubscriptionSummarySetting({ logicProps }: { logicProps: SubscriptionLogicProps }): JSX.Element {
    const { summaryQuota } = useValues(subscriptionLogic(logicProps))
    const summaryCopyVariant = useFeatureFlagVariantKey(FEATURE_FLAGS.SUBSCRIPTION_SUMMARY_COPY_EXPERIMENT)

    return (
        <LemonField name="summary_enabled">
            {({ value, onChange }) => (
                <LemonSwitch
                    checked={value}
                    onChange={(enabled) => {
                        onChange(enabled)
                        posthog.capture('subscription summary toggled', { enabled })
                    }}
                    disabledReason={
                        summaryQuota?.at_limit && !value
                            ? `Plan limit reached (${summaryQuota.limit} active AI summaries)`
                            : undefined
                    }
                    bordered
                    fullWidth
                    label={
                        <div className="flex flex-col gap-1 py-1">
                            <div className="leading-tight">
                                {summaryCopyVariant === 'summary'
                                    ? 'Include a report summary'
                                    : 'Include an automatic AI summary'}
                            </div>
                            <div className="text-xs text-secondary font-normal leading-tight">
                                {summaryCopyVariant === 'summary'
                                    ? 'Add an overview of the report to each delivery.'
                                    : 'Add an AI-written overview of the report to each delivery.'}
                            </div>
                        </div>
                    }
                />
            )}
        </LemonField>
    )
}
