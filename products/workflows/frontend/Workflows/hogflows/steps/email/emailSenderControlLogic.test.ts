/* oxlint-disable react-hooks/rules-of-hooks -- useMocks is a test helper, not a React hook */
import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { waitFor } from '@testing-library/react'
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { EditorRef, emailTemplaterLogic } from 'scenes/hog-functions/email-templater/emailTemplaterLogic'
import type { EmailTemplate } from 'scenes/hog-functions/email-templater/types'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { AccessControlLevel, IntegrationType } from '~/types'

import { sandboxSenderLogic } from '../../../../Channels/sandboxSenderLogic'
import { workflowLogic } from '../../../workflowLogic'
import type { HogFlow, HogFlowAction } from '../../types'
import { emailSenderControlLogic } from './emailSenderControlLogic'

const STATUS = {
    integration_id: 11,
    from_address: 'sandbox@example.com',
    display_name: 'Example via PostHog',
    organization_blocked: false,
    adoption_enabled: true,
}
const OWN_SENDER = { id: 7, kind: 'email', config: { verified: true } } as unknown as IntegrationType
const SECOND_SENDER = { id: 8, kind: 'email', config: { verified: true } } as unknown as IntegrationType
const VERIFYING_SENDER = { id: 9, kind: 'email', config: { verified: false } } as unknown as IntegrationType
const STOPPED_SENDER = {
    id: 10,
    kind: 'email',
    config: { verified: true, ses_sending_status: 'failed' },
} as unknown as IntegrationType

function ownStep(value: Record<string, any> = {}): HogFlowAction {
    return {
        id: 'email_step',
        type: 'function_email',
        name: 'Welcome',
        description: '',
        created_at: 0,
        updated_at: 0,
        config: {
            template_id: 'template-email',
            inputs: {
                email: {
                    templating: 'liquid',
                    value: { to: { email: '{{ person.properties.email }}' }, subject: 'Hi', from: {}, ...value },
                },
            },
        },
    } as HogFlowAction
}

const SANDBOX_STEP = {
    id: 'email_step',
    type: 'email_sandbox',
    name: 'Welcome',
    description: '',
    created_at: 0,
    updated_at: 0,
    config: {
        inputs: {
            email: { templating: 'liquid', value: { to: { email: '{{ person.properties.email }}' }, subject: 'Hi' } },
        },
    },
} as HogFlowAction

describe('emailSenderControlLogic', () => {
    let wfLogic: ReturnType<typeof workflowLogic.build>
    let logic: ReturnType<typeof emailSenderControlLogic.build>

    afterEach(() => {
        logic?.unmount()
        jest.useRealTimers()
    })

    async function setUp(
        step: HogFlowAction,
        status: Record<string, any> = STATUS,
        workflowInfo: Partial<HogFlow> = {},
        senders: IntegrationType[] = [VERIFYING_SENDER],
        defaultSenderId: number | null = null,
        { sendersLoadedFirst = false }: { sendersLoadedFirst?: boolean } = {}
    ): Promise<void> {
        initKeaTests(true, {
            ...MOCK_DEFAULT_TEAM,
            workflows_config: { ...MOCK_DEFAULT_TEAM.workflows_config, default_email_integration_id: defaultSenderId },
        })
        wfLogic = workflowLogic({ id: 'new' })
        wfLogic.mount()
        await expectLogic(wfLogic).toFinishAllListeners()
        wfLogic.actions.setWorkflowInfo({ ...workflowInfo, actions: [...wfLogic.values.workflow.actions, step] })
        if (workflowInfo.user_access_level) {
            wfLogic.actions.loadWorkflowSuccess({ ...wfLogic.values.workflow })
        }
        useMocks({
            get: {
                '/api/projects/:team_id/integrations/': { results: senders, next: null },
                '/api/projects/:team_id/workflow_email_sandbox/status/': status,
            },
        })
        integrationsLogic.mount()
        sandboxSenderLogic.mount()
        await expectLogic(integrationsLogic).toFinishAllListeners()
        sandboxSenderLogic.actions.loadSandboxStatusSuccess(status as any)
        if (sendersLoadedFirst) {
            integrationsLogic.actions.loadIntegrationsSuccess(senders)
        }
        logic = emailSenderControlLogic({ workflowLogicProps: wfLogic.props, actionId: step.id })
        logic.mount()
        if (!sendersLoadedFirst) {
            integrationsLogic.actions.loadIntegrationsSuccess(senders)
        }
        await expectLogic(logic).toFinishAllListeners()
    }

    function storedStep(): HogFlowAction | undefined {
        return wfLogic.values.workflow.actions.find((action) => action.id === 'email_step')
    }

    it('switches an own step without own-only settings to the sandbox sender without asking', async () => {
        await setUp(ownStep({ from: { integrationId: 7 } }))

        logic.actions.chooseSender('sandbox')

        expect(storedStep()).toMatchObject({ id: 'email_step', type: 'email_sandbox', name: 'Welcome' })
        expect(logic.values.pendingSwitch).toBeNull()
    })

    it.each([
        ['cancel', 'function_email'],
        ['confirm', 'email_sandbox'],
    ])('asks before dropping own-only settings, and %s decides the step kind', async (decision, expectedType) => {
        await setUp(
            ownStep({ from: { integrationId: 7, name: 'Support' }, replyTo: 'help@example.com', cc: 'a@example.com' })
        )

        logic.actions.chooseSender('sandbox')
        expect(logic.values.pendingSwitch).toEqual({ droppedSettings: ['sender_override', 'reply_to', 'cc_bcc'] })
        expect(storedStep()?.type).toEqual('function_email')

        const decide = decision === 'cancel' ? logic.actions.cancelSwitch : logic.actions.confirmSwitch
        decide()

        expect(logic.values.pendingSwitch).toBeNull()
        expect(storedStep()?.type).toEqual(expectedType)
    })

    it('switches a sandbox step to the chosen own sender', async () => {
        await setUp(SANDBOX_STEP, STATUS, {}, [OWN_SENDER, SECOND_SENDER])

        logic.actions.chooseSender(7)

        expect(storedStep()).toMatchObject({
            type: 'function_email',
            config: { template_id: 'template-email', inputs: { email: { value: { from: { integrationId: 7 } } } } },
        })
    })

    it.each<[string, HogFlowAction, Record<string, any>, boolean, Partial<HogFlow>]>([
        ['an own step when adoption is on and no sender is verified', ownStep(), STATUS, true, {}],
        ['an own step when adoption is off', ownStep(), { ...STATUS, adoption_enabled: false }, false, {}],
        [
            'an own step when the organization is blocked',
            ownStep(),
            { ...STATUS, organization_blocked: true },
            false,
            {},
        ],
        ['a sandbox step when adoption is off', SANDBOX_STEP, { ...STATUS, adoption_enabled: false }, true, {}],
        ['an own step in a workflow another product owns', ownStep(), STATUS, false, { origin_product: 'broadcasts' }],
        ['an own step whose id the sandbox sender rejects', { ...ownStep(), id: 'welcome.email' }, STATUS, false, {}],
    ])('offers the sandbox sender for %s', async (_, step, status, expected, workflowInfo) => {
        const capture = jest.spyOn(posthog, 'capture')

        await setUp(step, status, workflowInfo)

        expect(logic.values.showSandboxOption).toEqual(expected)
        expect(capture.mock.calls.filter(([event]) => event === 'workflows sandbox sender offered')).toEqual(
            expected ? [['workflows sandbox sender offered', { step_type: step.type }]] : []
        )
    })

    it('stops offering the sandbox sender on an own step once a sender is verified', async () => {
        await setUp(ownStep({ from: { integrationId: 7 } }), STATUS, {}, [OWN_SENDER])

        expect(logic.values.showSandboxOption).toEqual(false)
    })

    it.each<[string, IntegrationType[], number | null, Record<string, any>, Record<string, any>]>([
        [
            'the only verified sender',
            [OWN_SENDER, VERIFYING_SENDER],
            null,
            STATUS,
            {
                type: 'function_email',
                config: { inputs: { email: { value: { subject: 'Hi', from: { integrationId: 7 } } } } },
            },
        ],
        [
            "the project's default sender",
            [OWN_SENDER, SECOND_SENDER],
            8,
            STATUS,
            { type: 'function_email', config: { inputs: { email: { value: { from: { integrationId: 8 } } } } } },
        ],
        [
            'no sender when several are verified and none is the default',
            [OWN_SENDER, SECOND_SENDER],
            null,
            STATUS,
            { type: 'email_sandbox' },
        ],
        ['no sender when none is verified', [VERIFYING_SENDER], null, STATUS, { type: 'email_sandbox' }],
        [
            'no sender when adoption is off',
            [OWN_SENDER],
            null,
            { ...STATUS, adoption_enabled: false },
            { type: 'email_sandbox' },
        ],
        [
            'no sender when the only verified sender stopped sending',
            [STOPPED_SENDER],
            null,
            STATUS,
            { type: 'email_sandbox' },
        ],
        [
            'no sender when the project default is hidden from the editor',
            [OWN_SENDER],
            8,
            STATUS,
            { type: 'email_sandbox' },
        ],
    ])('moves a sandbox step to %s', async (_, senders, defaultSenderId, status, expected) => {
        await setUp(SANDBOX_STEP, status, {}, senders, defaultSenderId)

        expect(storedStep()).toMatchObject(expected)
    })

    it('moves a sandbox step whose senders loaded before its editor opened', async () => {
        await setUp(SANDBOX_STEP, STATUS, {}, [OWN_SENDER], null, { sendersLoadedFirst: true })

        expect(storedStep()).toMatchObject({ type: 'function_email' })
    })

    it('leaves a sandbox step and records no switch when the editor can only view the workflow', async () => {
        const capture = jest.spyOn(posthog, 'capture')

        await setUp(SANDBOX_STEP, STATUS, { user_access_level: AccessControlLevel.Viewer }, [OWN_SENDER])

        expect(storedStep()).toMatchObject({ type: 'email_sandbox' })
        expect(capture.mock.calls.filter(([event]) => event === 'workflows email sender changed')).toEqual([])
    })

    it('moves a sandbox step once a sender is verified in another tab and the editor returns', async () => {
        await setUp(SANDBOX_STEP, STATUS, {}, [VERIFYING_SENDER])
        useMocks({ get: { '/api/projects/:team_id/integrations/': { results: [OWN_SENDER], next: null } } })

        window.dispatchEvent(new Event('focus'))

        await waitFor(() => expect(storedStep()).toMatchObject({ type: 'function_email' }))
    })

    it('saves a pending canvas edit before moving a sandbox step', async () => {
        await setUp(SANDBOX_STEP, STATUS, {}, [VERIFYING_SENDER])
        const editorListeners: Record<string, () => void> = {}
        let editorDesign: Record<string, any> = { body: { id: 'stored', rows: [] } }
        const templater = emailTemplaterLogic({
            value: (SANDBOX_STEP.config as any).inputs.email.value,
            onChange: (email: EmailTemplate) => {
                const step = storedStep() as any
                wfLogic.actions.setWorkflowAction('email_step', {
                    ...step,
                    config: {
                        ...step.config,
                        inputs: { ...step.config.inputs, email: { templating: 'liquid', value: email } },
                    },
                })
            },
            type: 'native_email_sandbox',
            liveChanges: true,
        })
        templater.mount()
        templater.actions.setIsModalOpen(true)
        templater.actions.setEmailEditorRef({
            editor: {
                loadDesign: jest.fn(),
                registerProvider: jest.fn(),
                registerCallback: jest.fn(),
                addEventListener: (event: string, callback: () => void) => {
                    editorListeners[event] = callback
                },
                exportHtml: (callback: (data: any) => void) =>
                    callback({ html: '<p>edited</p>', design: editorDesign }),
                exportPlainText: (callback: (data: any) => void) => callback({ text: 'edited' }),
            },
        } as unknown as EditorRef)
        templater.actions.onEmailEditorReady()
        editorListeners['design:loaded']?.()
        await expectLogic(templater).toFinishAllListeners()

        jest.useFakeTimers()
        editorDesign = { body: { id: 'edited', rows: [] } }
        editorListeners['design:updated']()
        integrationsLogic.actions.loadIntegrationsSuccess([OWN_SENDER])

        await waitFor(() => expect(storedStep()).toMatchObject({ type: 'function_email' }))
        templater.unmount()
        expect(storedStep()).toMatchObject({ config: { inputs: { email: { value: { html: '<p>edited</p>' } } } } })
    })
})
