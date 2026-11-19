import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { BindLogic } from 'kea'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { IntegrationEmailDomainView } from '../../Channels/IntegrationEmailDomainView'
import { HogFlowFunctionConfiguration } from '../../Workflows/hogflows/steps/components/HogFlowFunctionConfiguration'
import { workflowLogic } from '../../Workflows/workflowLogic'
import { WorkflowsDailyLimitsSettings } from './WorkflowsDailyLimitsSettings'
import { WorkflowsEmailTrackingConsentSettings } from './WorkflowsEmailTrackingConsentSettings'
import { WorkflowsEngagementEventsSettings } from './WorkflowsEngagementEventsSettings'
import { WorkflowsFrequencyCapSettings } from './WorkflowsFrequencyCapSettings'

const OTHER_TAB_CONFIG = { capture_workflows_engagement_events: true, email_tracking_consent_mode: 'opt_in' }
// Engagement stays off here, so a save that drops the flag it turns on fails too.
const OTHER_TAB_CONSENT_ONLY = { capture_workflows_engagement_events: false, email_tracking_consent_mode: 'opt_in' }

function setNumber(dataAttr: string, value: string): void {
    fireEvent.change(document.querySelector(`[data-attr="${dataAttr}"]`) as HTMLInputElement, { target: { value } })
}

describe('workflows settings save', () => {
    let storedConfig: Record<string, any>
    let saves: number

    beforeEach(() => {
        // Another tab saved both settings after this tab loaded the team.
        storedConfig = { ...OTHER_TAB_CONFIG }
        saves = 0
        useMocks({
            get: {
                '/api/projects/:team_id/hog_function_templates/': {
                    results: [{ id: 'template-email', name: 'Email', type: 'destination', inputs_schema: [] }],
                    count: 1,
                    next: null,
                },
            },
            patch: {
                '/api/environments/:team_id/': async ({ request }) => {
                    const body = (await request.json()) as Record<string, any>
                    Object.assign(storedConfig, body.workflows_config)
                    saves += 1
                    return [200, { ...MOCK_DEFAULT_TEAM, workflows_config: { ...storedConfig } }]
                },
            },
        })
        initKeaTests(true, {
            ...MOCK_DEFAULT_TEAM,
            workflows_config: { capture_workflows_engagement_events: false, email_tracking_consent_mode: 'off' },
        })
    })

    afterEach(() => {
        cleanup()
    })

    it.each([
        {
            setting: 'the consent mode',
            renderSetting: () => render(<WorkflowsEmailTrackingConsentSettings />),
            save: () => fireEvent.click(screen.getByText('Opt-out')),
            saved: { email_tracking_consent_mode: 'opt_out' },
        },
        {
            setting: 'engagement events',
            renderSetting: () => render(<WorkflowsEngagementEventsSettings />),
            save: () => fireEvent.click(screen.getByText('Capture email engagement events')),
            otherTab: OTHER_TAB_CONSENT_ONLY,
            saved: { capture_workflows_engagement_events: true },
        },
        {
            setting: 'daily limits',
            renderSetting: () =>
                render(
                    <WorkflowsDailyLimitsSettings
                        perWorkflowField="workflow_task_rate_limit_per_day"
                        perProjectField="workflow_task_team_rate_limit_per_day"
                        defaultPerWorkflow={100}
                        defaultPerProject={500}
                        unit="tasks"
                        attrPrefix="workflows-task"
                    />
                ),
            save: () => {
                setNumber('workflows-task-limit-per-workflow', '50')
                fireEvent.click(screen.getByText('Save'))
            },
            saved: { workflow_task_rate_limit_per_day: 50, workflow_task_team_rate_limit_per_day: null },
        },
        {
            setting: 'the frequency cap',
            renderSetting: () => render(<WorkflowsFrequencyCapSettings />),
            save: () => {
                setNumber('workflows-frequency-cap-max-messages', '3')
                setNumber('workflows-frequency-cap-window-days', '7')
                fireEvent.click(screen.getByText('Save'))
            },
            saved: {
                marketing_frequency_cap_max_messages: 3,
                marketing_frequency_cap_window_days: 7,
                marketing_frequency_cap_hold_hours: null,
            },
        },
        {
            setting: 'the default sender',
            renderSetting: () =>
                render(
                    <IntegrationEmailDomainView
                        integration={{
                            domain: 'example.com',
                            integrations: [
                                {
                                    id: 7,
                                    kind: 'email',
                                    display_name: 'hello@example.com',
                                    icon_url: '',
                                    config: { verified: true, name: 'Hello', email: 'hello@example.com' },
                                    created_at: '2026-11-01T00:00:00Z',
                                },
                            ],
                        }}
                    />
                ),
            save: () => {
                fireEvent.click(screen.getByText('example.com'))
                fireEvent.click(screen.getByText('Make default'))
            },
            saved: { default_email_integration_id: 7 },
        },
        {
            setting: 'engagement events from the email step',
            renderSetting: async () => {
                const logic = workflowLogic({ id: 'new' })
                logic.mount()
                await waitFor(() => expect(logic.values.hogFunctionTemplatesById['template-email']).toBeTruthy())
                render(
                    <BindLogic logic={workflowLogic} props={{ id: 'new' }}>
                        <HogFlowFunctionConfiguration templateId="template-email" inputs={{}} setInputs={() => {}} />
                    </BindLogic>
                )
            },
            save: async () => fireEvent.click(await screen.findByText('Enable engagement events')),
            otherTab: OTHER_TAB_CONSENT_ONLY,
            saved: { capture_workflows_engagement_events: true },
        },
    ])('saving $setting keeps what another tab saved', async ({ renderSetting, save, otherTab, saved }) => {
        storedConfig = { ...(otherTab ?? OTHER_TAB_CONFIG) }
        await renderSetting()

        await save()

        await waitFor(() => expect(saves).toBe(1))
        expect(storedConfig).toEqual({ ...(otherTab ?? OTHER_TAB_CONFIG), ...saved })
    })
})
