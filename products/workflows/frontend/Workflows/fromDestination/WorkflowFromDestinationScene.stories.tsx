import { Meta, StoryFn } from '@storybook/react'
import { router } from 'kea-router'
import { useEffect } from 'react'

import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

import { WorkflowFromDestinationStep, workflowFromDestinationLogic } from './workflowFromDestinationLogic'

const TEMPLATE_ID = 'template-slack'

const SLACK_TEMPLATE = {
    id: TEMPLATE_ID,
    type: 'destination',
    name: 'Slack',
    description: 'Sends a message to a Slack channel',
    status: 'stable',
    free: true,
    icon_url: '/static/services/slack.png',
    code: '',
    code_language: 'hog',
    filters: null,
    inputs_schema: [
        { key: 'slack_workspace', type: 'integration', integration: 'slack', label: 'Slack workspace', required: true },
        {
            key: 'channel',
            type: 'integration_field',
            integration_key: 'slack_workspace',
            integration_field: 'slack_channel',
            label: 'Channel to post to',
            required: true,
        },
        { key: 'icon_emoji', type: 'string', label: 'Emoji icon', default: ':hedgehog:', required: false },
        { key: 'username', type: 'string', label: 'Bot name', default: 'PostHog', required: false },
        {
            key: 'text',
            type: 'string',
            label: 'Message text',
            default: "*{person.name}* triggered event: '{event.event}'",
            required: false,
        },
    ],
}

const SLACK_INTEGRATION = {
    id: 1,
    kind: 'slack',
    display_name: 'Example workspace',
    icon_url: '/static/services/slack.png',
    config: { team: { name: 'Example workspace' } },
    created_at: '2026-09-01T00:00:00Z',
}

const meta: Meta = {
    title: 'Scenes-App/Workflows/WorkflowFromDestination',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2026-09-30',
    },
    decorators: [
        mswDecorator({
            get: {
                [`/api/projects/:team_id/hog_function_templates/${TEMPLATE_ID}/`]: SLACK_TEMPLATE,
                '/api/projects/:team_id/integrations/': { results: [SLACK_INTEGRATION] },
                '/api/environments/:team_id/integrations/:id/channels': {
                    channels: [
                        { id: 'C0123ABC', name: 'general', is_private: false, is_ext_shared: false, is_member: true },
                    ],
                },
            },
        }),
    ],
}
export default meta

function WizardAtStep({ step }: { step: WorkflowFromDestinationStep }): JSX.Element {
    useEffect(() => {
        // Mount the keyed logic before the scene does so the persisted reducers already hold the
        // progress the story wants to show; the scene then attaches to this same instance.
        const logic = workflowFromDestinationLogic({ templateId: TEMPLATE_ID })
        const unmount = logic.mount()
        logic.actions.resetWizard()
        if (step !== 'trigger') {
            logic.actions.setTriggerFilters({ events: [{ id: '$pageview', name: '$pageview', type: 'events' }] })
        }
        if (step === 'message') {
            logic.actions.setInputs({
                slack_workspace: { value: SLACK_INTEGRATION.id },
                channel: { value: 'C0123ABC' },
                icon_emoji: { value: ':hedgehog:' },
                username: { value: 'PostHog' },
                text: { value: "*{person.name}* triggered event: '{event.event}'" },
            })
        }
        logic.actions.setStep(step)
        router.actions.push(urls.workflowNewFromDestination(TEMPLATE_ID))
        return unmount
    }, [step])
    return <App />
}

export const TriggerStep: StoryFn = () => <WizardAtStep step="trigger" />

export const ConnectStep: StoryFn = () => <WizardAtStep step="connect" />

export const MessageStep: StoryFn = () => <WizardAtStep step="message" />

export const TriggerStepNarrow: StoryFn = () => <WizardAtStep step="trigger" />
// A docked side panel leaves a scene roughly this wide; the wizard has to hold up there.
TriggerStepNarrow.parameters = { testOptions: { viewport: { width: 800, height: 1200 } } }
