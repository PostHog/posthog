import { expectLogic } from 'kea-test-utils'

import { integrationsLogic } from 'lib/integrations/integrationsLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { messageTemplateLogic } from './messageTemplateLogic'
import { messageTemplateTestSendLogic } from './messageTemplateTestSendLogic'

jest.mock('lib/lemon-ui/LemonToast', () => ({
    lemonToast: {
        success: jest.fn(),
        warning: jest.fn(),
        error: jest.fn(),
    },
}))

const mockToast = require('lib/lemon-ui/LemonToast').lemonToast

describe('messageTemplateTestSendLogic', () => {
    let logic: ReturnType<typeof messageTemplateTestSendLogic.build>
    let templateLogic: ReturnType<typeof messageTemplateLogic.build>
    let capturedBody: any

    beforeEach(async () => {
        jest.clearAllMocks()
        capturedBody = null

        useMocks({
            get: {
                '/api/environments/:team_id/integrations/': {
                    results: [
                        {
                            id: 4,
                            kind: 'email',
                            display_name: 'Unverified sender <unverified@example.com>',
                            config: { verified: false },
                        },
                        {
                            id: 5,
                            kind: 'email',
                            display_name: 'Sender <sender@example.com>',
                            config: { verified: true },
                        },
                        { id: 6, kind: 'slack', display_name: 'Slack' },
                    ],
                },
            },
            post: {
                '/api/environments/:team_id/hog_flows/:id/invocations/': async ({ request }: { request: Request }) => {
                    capturedBody = await request.json()
                    return [200, { status: 'success', nextActionId: null }]
                },
            },
        })

        initKeaTests()

        templateLogic = messageTemplateLogic({ id: 'new' })
        templateLogic.mount()
        templateLogic.actions.setTemplateValue('content.email.subject', 'Welcome')

        logic = messageTemplateTestSendLogic({ id: 'new' })
        logic.mount()

        // The sender select defaults to the first email integration once it loads.
        await expectLogic(integrationsLogic).toDispatchActions(['loadIntegrationsSuccess'])
    })

    afterEach(() => {
        logic?.unmount()
        templateLogic?.unmount()
    })

    it('prefills the recipient with the current user email when the modal opens', async () => {
        await expectLogic(logic, () => {
            logic.actions.setModalOpen(true)
        }).toMatchValues({ recipientEmail: 'john.doe@posthog.com' })
    })

    it('defaults the sender to the first verified email integration, excluding unverified and non-email kinds', async () => {
        await expectLogic(logic).toMatchValues({
            senderIntegrationId: 5,
            emailIntegrations: [expect.objectContaining({ id: 5 })],
        })
    })

    it('sends a one-step synthetic workflow carrying the typed recipient and template content, stripping any cc/bcc', async () => {
        templateLogic.actions.setTemplateValue('content.email.cc', 'observer@example.com')
        templateLogic.actions.setTemplateValue('content.email.bcc', 'archive@example.com')
        logic.actions.setRecipientEmail('recipient@example.com')

        await expectLogic(logic, () => {
            logic.actions.sendTestEmail()
        }).toDispatchActions(['sendTestEmailSuccess'])

        expect(capturedBody.mock_async_functions).toBe(false)
        expect(capturedBody.current_action_id).toBe('send_test_email')
        expect(capturedBody.configuration.actions.filter((a: any) => a.type === 'trigger')).toHaveLength(1)

        const emailAction = capturedBody.configuration.actions.find((a: any) => a.type === 'function_email')
        expect(emailAction.config.inputs.email.value).toMatchObject({
            subject: 'Welcome',
            to: { email: 'recipient@example.com', name: '' },
            from: { integrationId: 5 },
            cc: '',
            bcc: '',
        })

        expect(mockToast.success).toHaveBeenCalledWith('Test email sent to recipient@example.com')
        expect(logic.values.isModalOpen).toBe(false)
    })

    it('treats a skipped send as a distinct outcome from a failure', async () => {
        useMocks({
            post: {
                '/api/environments/:team_id/hog_flows/:id/invocations/': () => [
                    200,
                    { status: 'skipped', logs: [{ message: 'Recipient has opted out.' }] },
                ],
            },
        })

        logic.actions.setModalOpen(true)
        logic.actions.setRecipientEmail('recipient@example.com')

        await expectLogic(logic, () => {
            logic.actions.sendTestEmail()
        }).toDispatchActions(['sendTestEmailSuccess'])

        expect(mockToast.warning).toHaveBeenCalledWith('Test email skipped, see details below')
        expect(mockToast.error).not.toHaveBeenCalled()
        expect(logic.values.isModalOpen).toBe(true)
        expect(logic.values.testSendResult?.status).toBe('skipped')
    })

    it('keeps the modal open and surfaces the error when the send fails', async () => {
        useMocks({
            post: {
                '/api/environments/:team_id/hog_flows/:id/invocations/': () => [
                    200,
                    { status: 'error', errors: ['The selected email integration domain is not verified'] },
                ],
            },
        })

        logic.actions.setModalOpen(true)
        logic.actions.setRecipientEmail('recipient@example.com')

        await expectLogic(logic, () => {
            logic.actions.sendTestEmail()
        }).toDispatchActions(['sendTestEmailSuccess'])

        expect(mockToast.error).toHaveBeenCalledWith('Failed to send test email')
        expect(logic.values.isModalOpen).toBe(true)
        expect(logic.values.testSendResult?.errors).toEqual(['The selected email integration domain is not verified'])
    })

    it('disables sending until subject, body, recipient, and sender are all valid', async () => {
        templateLogic.actions.setTemplateValue('content.email.subject', '')
        await expectLogic(logic).toMatchValues({ sendDisabledReason: 'Add a subject first' })

        templateLogic.actions.setTemplateValue('content.email.subject', 'Welcome')
        templateLogic.actions.setTemplateValue('content.email.text', '')
        templateLogic.actions.setTemplateValue('content.email.html', '')
        await expectLogic(logic).toMatchValues({ sendDisabledReason: 'Add email content first' })

        templateLogic.actions.setTemplateValue('content.email.text', 'Hello!')
        logic.actions.setRecipientEmail('not-an-email')
        await expectLogic(logic).toMatchValues({ sendDisabledReason: 'Enter a valid email address' })

        logic.actions.setRecipientEmail('recipient@example.com')
        await expectLogic(logic).toMatchValues({ sendDisabledReason: undefined })
    })

    it('does not crash when a template has no email content, and disables sending', async () => {
        templateLogic.actions.setTemplateValue('content.email', undefined)

        await expectLogic(logic).toMatchValues({ sendDisabledReason: 'Add a subject first' })
    })
})
