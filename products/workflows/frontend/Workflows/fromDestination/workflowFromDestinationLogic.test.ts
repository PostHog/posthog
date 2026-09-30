import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { removeProjectIdIfPresent } from 'lib/utils/kea-router'
import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { HogFunctionTemplateType } from '~/types'

import { TRIGGER_TARGET_ERROR, WIZARD_STATE_TTL_MS, workflowFromDestinationLogic } from './workflowFromDestinationLogic'

const SLACK_TEMPLATE = {
    id: 'template-slack',
    type: 'destination',
    name: 'Slack',
    description: 'Sends a message to a Slack channel',
    status: 'stable',
    free: true,
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
        { key: 'text', type: 'string', label: 'Message text', required: false },
    ],
} as unknown as HogFunctionTemplateType

const DISCORD_TEMPLATE = {
    ...SLACK_TEMPLATE,
    id: 'template-discord',
    name: 'Discord',
    description: 'Sends a message to a Discord channel',
    inputs_schema: [
        { key: 'webhookUrl', type: 'string', label: 'Webhook URL', required: true },
        { key: 'content', type: 'string', label: 'Content', default: 'Hello from PostHog', required: true },
    ],
} as unknown as HogFunctionTemplateType

const PAGEVIEW_TRIGGER = { events: [{ id: '$pageview', name: '$pageview', type: 'events' }] }

describe('workflowFromDestinationLogic', () => {
    let logic: ReturnType<typeof workflowFromDestinationLogic.build>
    let createBodies: Record<string, any>[]

    async function mountLoaded(templateId: string): Promise<void> {
        logic = workflowFromDestinationLogic({ templateId })
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadTemplateSuccess']).toFinishAllListeners()
    }

    beforeEach(() => {
        createBodies = []
        // The wizard persists its state, so a previous test's progress must not leak into this one.
        localStorage.clear()
        useMocks({
            get: {
                '/api/projects/:team_id/hog_function_templates/template-slack/': SLACK_TEMPLATE,
                '/api/projects/:team_id/hog_function_templates/template-discord/': DISCORD_TEMPLATE,
            },
            post: {
                '/api/projects/:team_id/hog_flows/': async ({ request }) => {
                    const body = (await request.json()) as Record<string, any>
                    createBodies.push(body)
                    return [201, { ...body, id: 'wf-1' }]
                },
            },
            patch: {
                '/api/projects/@current/add_product_intent/': {},
            },
        })
        initKeaTests()
    })

    afterEach(() => {
        logic?.unmount()
        jest.restoreAllMocks()
    })

    it.each([
        ['template-slack', ['trigger', 'connect', 'message']],
        ['template-discord', ['trigger', 'message']],
    ])('%s only gets a connect step when the template has an integration input', async (templateId, steps) => {
        await mountLoaded(templateId)
        expect(logic.values.steps).toEqual(steps)
    })

    it('seeds the message inputs from the template defaults and hides the integration input on the message step', async () => {
        await mountLoaded('template-slack')
        expect(logic.values.inputs).toEqual({ icon_emoji: { value: ':hedgehog:' } })
        expect(logic.values.name).toEqual('Slack notification')
        expect(logic.values.messageInputsSchema.map((schema) => [schema.key, !!schema.hidden])).toEqual([
            ['slack_workspace', true],
            ['channel', false],
            ['icon_emoji', false],
            ['text', false],
        ])
    })

    it('stays on the trigger step until an event, action or property is picked', async () => {
        await mountLoaded('template-slack')

        logic.actions.goToNextStep()
        expect(logic.values.currentStep).toEqual('trigger')
        expect(logic.values.stepErrors).toEqual({ trigger: [TRIGGER_TARGET_ERROR] })

        logic.actions.setTriggerFilters(PAGEVIEW_TRIGGER)
        logic.actions.goToNextStep()
        expect(logic.values.currentStep).toEqual('connect')
        expect(logic.values.stepErrors).toEqual({})
    })

    it('applies the integration from the OAuth return as a number and strips the params from the URL', async () => {
        router.actions.push(urls.workflowNewFromDestination('template-slack'), {
            integration_id: '123',
            integration_target: 'slack_workspace',
        })

        await mountLoaded('template-slack')

        expect(logic.values.inputs?.slack_workspace).toEqual({ value: 123 })
        expect(removeProjectIdIfPresent(router.values.location.pathname)).toEqual(
            urls.workflowNewFromDestination('template-slack')
        )
        expect(router.values.searchParams).toEqual({})
    })

    it('creates a draft from the defaults merged under the user inputs and opens the editor on the message step', async () => {
        await mountLoaded('template-slack')
        logic.actions.setTriggerFilters(PAGEVIEW_TRIGGER)
        logic.actions.setInput('slack_workspace', { value: 5 })
        logic.actions.setInput('channel', { value: 'C0123ABC' })

        logic.actions.submitWizard()
        await expectLogic(logic).toDispatchActions(['createWorkflowSuccess']).toFinishAllListeners()

        expect(createBodies).toHaveLength(1)
        const [body] = createBodies
        const functionAction = body.actions[1]
        expect(body).toMatchObject({ name: 'Slack notification', status: 'draft' })
        expect(body.actions[0].config).toEqual({ type: 'event', filters: PAGEVIEW_TRIGGER })
        expect(functionAction.config.template_id).toEqual('template-slack')
        expect(functionAction.config.inputs).toMatchObject({
            slack_workspace: { value: 5 },
            channel: { value: 'C0123ABC' },
            icon_emoji: { value: ':hedgehog:' },
        })
        expect(removeProjectIdIfPresent(router.values.location.pathname)).toEqual(urls.workflow('wf-1', 'workflow'))
        expect(router.values.searchParams).toEqual({ node: functionAction.id })
        // The persisted state is cleared so the next visit starts a fresh wizard.
        expect(logic.values.currentStep).toEqual('trigger')
        expect(logic.values.inputs).toBeNull()
    })

    it('jumps to the step with a missing required input instead of creating the workflow', async () => {
        await mountLoaded('template-slack')
        logic.actions.setTriggerFilters(PAGEVIEW_TRIGGER)
        logic.actions.setInput('slack_workspace', { value: 5 })
        logic.actions.setStep('trigger')

        logic.actions.submitWizard()
        await expectLogic(logic).toFinishAllListeners()

        expect(createBodies).toHaveLength(0)
        expect(logic.values.currentStep).toEqual('message')
        expect(logic.values.stepErrors).toEqual({ message: ['This field is required.'] })
    })

    it('discards persisted progress older than the TTL unless returning from OAuth', async () => {
        await mountLoaded('template-slack')
        logic.actions.setTriggerFilters(PAGEVIEW_TRIGGER)
        logic.actions.setStep('connect')
        logic.unmount()

        const later = Date.now() + WIZARD_STATE_TTL_MS + 1
        jest.spyOn(Date, 'now').mockReturnValue(later)
        await mountLoaded('template-slack')

        expect(logic.values.currentStep).toEqual('trigger')
        expect(logic.values.triggerFilters).toEqual({})
        expect(logic.values.startedAt).toEqual(later)
    })
})
