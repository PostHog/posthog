import { useActions, useValues } from 'kea'

import { LemonTextArea, Link } from '@posthog/lemon-ui'

import { IntegrationChoice } from 'lib/components/CyclotronJob/integrations/IntegrationChoice'
import { usersLemonSelectOptions } from 'lib/components/UserSelectItem'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { SlackChannelPicker, SlackNotConfiguredBanner } from 'lib/integrations/SlackIntegrationHelpers'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInputSelect } from 'lib/lemon-ui/LemonInputSelect/LemonInputSelect'
import { LemonSelect } from 'lib/lemon-ui/LemonSelect'
import { preflightLogic } from 'lib/logic/preflightLogic'
import { membersLogic } from 'scenes/organization/membersLogic'

import { subscriptionLogic } from './subscriptionLogic'
import type { SubscriptionFormType, SubscriptionLogicProps } from './subscriptionLogic'
import { targetTypeOptions } from './utils'

export function SubscriptionNotifySection({
    logicProps,
    subscription,
}: {
    logicProps: SubscriptionLogicProps
    subscription: SubscriptionFormType
}): JSX.Element {
    const { meFirstMembers, membersLoading } = useValues(membersLogic)
    const { integrations, slackIntegrations } = useValues(integrationsLogic)
    const { preflight } = useValues(preflightLogic)
    const { setSubscriptionValue } = useActions(subscriptionLogic(logicProps))

    return (
        <div className="flex min-w-0 flex-col gap-4">
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
                    <LemonField
                        name="target_value"
                        label="Recipients"
                        help="Enter the email addresses that should receive this report."
                    >
                        {({ value, onChange }) => (
                            <LemonInputSelect
                                value={value?.split(',').filter(Boolean)}
                                onChange={(recipients) => onChange(recipients.join(','))}
                                mode="multiple"
                                allowCustomValues
                                options={usersLemonSelectOptions(meFirstMembers.map((member) => member.user))}
                                loading={membersLoading}
                                placeholder="Enter an email address"
                                data-attr="subscribed-emails"
                            />
                        )}
                    </LemonField>
                    <LemonField name="invite_message" label="Message" showOptional>
                        <LemonTextArea placeholder="Add a short note for recipients" />
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
                            <LemonField
                                name="target_value"
                                label="Slack channel"
                                help="Private channels appear after the PostHog Slack app has been added to them."
                            >
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
