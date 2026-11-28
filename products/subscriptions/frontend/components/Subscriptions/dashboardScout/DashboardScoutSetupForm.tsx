import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { SlackNotConfiguredBanner } from 'lib/integrations/SlackIntegrationHelpers'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonCollapse } from 'lib/lemon-ui/LemonCollapse'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { LemonRadio } from 'lib/lemon-ui/LemonRadio'
import { LemonSelect } from 'lib/lemon-ui/LemonSelect'
import { LemonTextArea } from 'lib/lemon-ui/LemonTextArea'
import { Link } from 'lib/lemon-ui/Link'
import { teamLogic } from 'scenes/teamLogic'

import { ScoutSlackDestination } from 'products/signals/frontend/inbox/components/config/scouts/ScoutSlackDestination'

import { DASHBOARD_SCOUT_CADENCE_OPTIONS, DASHBOARD_SCOUT_TIME_OPTIONS, DashboardScoutPostMode } from './dashboardScout'
import { DashboardScoutLogicProps, dashboardScoutLogic } from './dashboardScoutLogic'

const POST_MODE_OPTIONS: { value: DashboardScoutPostMode; label: string; description: string }[] = [
    {
        value: 'on_change',
        label: 'Only when something interesting happens',
        description: 'No message on a run where every insight is in its normal range.',
    },
    {
        value: 'every_run',
        label: 'Every run',
        description: 'A short update each time, including when nothing changed.',
    },
    {
        value: 'custom',
        label: 'In your own words',
        description: 'Describe when you want to hear from it.',
    },
]

export function DashboardScoutSetupForm(props: DashboardScoutLogicProps): JSX.Element {
    const logic = dashboardScoutLogic(props)
    const { scoutSetup, isScoutSetupSubmitting, instructionsPreview } = useValues(logic)
    const { closeSetup } = useActions(logic)
    const { slackIntegrations, integrationsLoading: slackIntegrationsLoading } = useValues(integrationsLogic)
    const { timezone } = useValues(teamLogic)

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
                {!slackIntegrationsLoading && !slackIntegrations?.length ? (
                    <SlackNotConfiguredBanner />
                ) : (
                    <LemonField name="destination" label="Post to">
                        {({ value, onChange }) => (
                            <ScoutSlackDestination
                                destination={value}
                                onChange={(outputDestinations) => onChange(outputDestinations.slack ?? null)}
                            />
                        )}
                    </LemonField>
                )}
                <div className="flex flex-wrap gap-4">
                    <LemonField name="cadence" label="Runs" className="flex-1 min-w-40">
                        <LemonSelect options={DASHBOARD_SCOUT_CADENCE_OPTIONS} fullWidth />
                    </LemonField>
                    <LemonField
                        name="time"
                        label="At"
                        help={`Uses the project timezone (${timezone}). Starts within 20 minutes of this time.`}
                        className="flex-1 min-w-40"
                    >
                        <LemonSelect options={DASHBOARD_SCOUT_TIME_OPTIONS} fullWidth />
                    </LemonField>
                </div>
                <LemonField name="postMode" label="When should it post?">
                    {({ value, onChange }) => (
                        <LemonRadio value={value} onChange={onChange} options={POST_MODE_OPTIONS} />
                    )}
                </LemonField>
                {scoutSetup.postMode === 'custom' ? (
                    <LemonField name="postPrompt" label="When should it post?" labelClassName="sr-only">
                        <LemonTextArea
                            placeholder="For example: a summary every Monday, and on other days only if signups drop by more than 10%."
                            minRows={2}
                            maxLength={500}
                            data-attr="dashboard-scout-post-prompt"
                        />
                    </LemonField>
                ) : null}
                <LemonField name="focus" label="What should it pay attention to?" showOptional>
                    <LemonTextArea
                        placeholder="For example: signup conversion matters most. Ignore weekend dips."
                        minRows={2}
                        maxLength={1000}
                    />
                </LemonField>
                <LemonCollapse
                    panels={[
                        {
                            key: 'instructions',
                            header: 'Scout instructions',
                            content: (
                                <div className="flex flex-col gap-2">
                                    <p className="text-xs text-secondary mb-0">
                                        What the scout follows on each run. You can edit this on the scout's page after
                                        you create it.
                                    </p>
                                    <pre
                                        className="m-0 max-h-80 overflow-y-auto whitespace-pre-wrap text-xs"
                                        data-attr="dashboard-scout-instructions-preview"
                                    >
                                        {instructionsPreview}
                                    </pre>
                                </div>
                            ),
                        },
                    ]}
                />
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
