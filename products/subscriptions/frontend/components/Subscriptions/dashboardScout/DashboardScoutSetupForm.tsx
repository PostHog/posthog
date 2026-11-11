import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { IntegrationChoice } from 'lib/components/CyclotronJob/integrations/IntegrationChoice'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { SlackChannelPicker, SlackNotConfiguredBanner } from 'lib/integrations/SlackIntegrationHelpers'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { LemonRadio } from 'lib/lemon-ui/LemonRadio'
import { LemonSelect } from 'lib/lemon-ui/LemonSelect'
import { LemonTextArea } from 'lib/lemon-ui/LemonTextArea'
import { Link } from 'lib/lemon-ui/Link'

import { DASHBOARD_SCOUT_CADENCE_OPTIONS, DASHBOARD_SCOUT_TIME_OPTIONS, DashboardScoutPostMode } from './dashboardScout'
import { DashboardScoutLogicProps, dashboardScoutLogic } from './dashboardScoutLogic'

const POST_MODE_OPTIONS: { value: DashboardScoutPostMode; label: string; description: string }[] = [
    {
        value: 'every_run',
        label: 'Every run',
        description: 'A short update each time, including when nothing changed.',
    },
    {
        value: 'on_change',
        label: 'Only when something changes',
        description: 'No message on a run where every insight is in its normal range.',
    },
]

export function DashboardScoutSetupForm(props: DashboardScoutLogicProps): JSX.Element {
    const logic = dashboardScoutLogic(props)
    const { scoutSetup, isScoutSetupSubmitting } = useValues(logic)
    const { closeSetup, setScoutSetupValue } = useActions(logic)
    const { integrations, slackIntegrations } = useValues(integrationsLogic)
    const integration = integrations?.find((item) => item.id === scoutSetup.integrationId)

    return (
        <Form logic={dashboardScoutLogic} props={props} formKey="scoutSetup" enableFormOnSubmit>
            <LemonModal.Header>
                <div>
                    <h3>Set up a scout for {props.dashboardName || 'this dashboard'}</h3>
                    <p className="text-sm text-secondary mb-0">
                        A scout is an agent that reads this dashboard on a schedule and posts what changed in Slack. You
                        can change these settings later.
                    </p>
                </div>
            </LemonModal.Header>
            <LemonModal.Content className="flex flex-col gap-4">
                {!slackIntegrations?.length ? (
                    <SlackNotConfiguredBanner />
                ) : (
                    <>
                        <LemonField name="integrationId" label="Slack connection">
                            {({ value, onChange }) => (
                                <IntegrationChoice
                                    integration="slack"
                                    value={value}
                                    onChange={(integrationId) => {
                                        onChange(integrationId)
                                        if (integrationId !== value) {
                                            setScoutSetupValue('channel', '')
                                        }
                                    }}
                                />
                            )}
                        </LemonField>
                        {integration ? (
                            <LemonField name="channel" label="Slack channel">
                                {({ value, onChange }) => (
                                    <SlackChannelPicker value={value} onChange={onChange} integration={integration} />
                                )}
                            </LemonField>
                        ) : null}
                    </>
                )}
                <div className="flex flex-wrap gap-4">
                    <LemonField name="cadence" label="Runs" className="flex-1 min-w-40">
                        <LemonSelect options={DASHBOARD_SCOUT_CADENCE_OPTIONS} fullWidth />
                    </LemonField>
                    <LemonField name="time" label="At" help="In the project's timezone." className="flex-1 min-w-40">
                        <LemonSelect options={DASHBOARD_SCOUT_TIME_OPTIONS} fullWidth />
                    </LemonField>
                </div>
                <LemonField name="postMode" label="When should it post?">
                    {({ value, onChange }) => (
                        <LemonRadio value={value} onChange={onChange} options={POST_MODE_OPTIONS} />
                    )}
                </LemonField>
                <LemonField name="focus" label="What should it pay attention to?" showOptional>
                    <LemonTextArea
                        placeholder="For example: signup conversion matters most. Ignore weekend dips."
                        minRows={2}
                        maxLength={1000}
                    />
                </LemonField>
                <p className="text-xs text-secondary mb-0">
                    Each run uses AI credits.{' '}
                    <Link to="https://posthog.com/docs/self-driving/scouts" target="_blank" targetBlankIcon>
                        Learn how scouts work
                    </Link>
                </p>
            </LemonModal.Content>
            <LemonModal.Footer>
                <LemonButton type="secondary" onClick={closeSetup} data-attr="dashboard-scout-setup-back">
                    Back
                </LemonButton>
                <LemonButton
                    type="primary"
                    htmlType="submit"
                    loading={isScoutSetupSubmitting}
                    data-attr="dashboard-scout-create"
                >
                    Create scout
                </LemonButton>
            </LemonModal.Footer>
        </Form>
    )
}
