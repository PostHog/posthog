import { MOCK_DEFAULT_ORGANIZATION_MEMBER, MOCK_SECOND_BASIC_USER, MOCK_SECOND_ORGANIZATION_MEMBER } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { membersLogic } from 'scenes/organization/membersLogic'

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
                '/api/projects/:team_id/integrations/': {
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

    it('leaves the recipient empty with the sandbox flag on, so the member suggestions show with the user first', async () => {
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.WORKFLOWS_SANDBOX_SENDER], {
            [FEATURE_FLAGS.WORKFLOWS_SANDBOX_SENDER]: true,
        })
        try {
            await expectLogic(logic, () => {
                logic.actions.setModalOpen(true)
            })
                .toDispatchActions(membersLogic, ['loadAllMembersSuccess'])
                .toMatchValues({ recipientEmail: '' })
            expect(logic.values.recipientSuggestions[0]).toBe('john.doe@posthog.com')
        } finally {
            featureFlagLogic.actions.setFeatureFlags([], {})
        }
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
        expect(logic.values.testSendSkipMessage).toBe('Recipient has opted out.')
    })

    describe('sandbox sender', () => {
        const SANDBOX_SENDER = {
            id: 7,
            kind: 'email',
            display_name: 'Acme via PostHog <sandbox@example.com>',
            config: { provider: 'sandbox', name: 'Acme via PostHog', email: 'sandbox@example.com', verified: true },
        }
        const UNVERIFIED_OWN_SENDER = {
            id: 4,
            kind: 'email',
            display_name: 'Unverified sender <unverified@example.com>',
            config: { verified: false },
        }
        const VERIFIED_OWN_SENDER = {
            id: 5,
            kind: 'email',
            display_name: 'Sender <sender@example.com>',
            config: { verified: true },
        }
        let ensureCalls: number
        let integrationsPayload: Record<string, any>[]

        const loadIntegrations = async (integrations: Record<string, any>[]): Promise<void> => {
            integrationsPayload = integrations
            await expectLogic(integrationsLogic, () => {
                integrationsLogic.actions.loadIntegrations()
            }).toDispatchActions(['loadIntegrationsSuccess'])
        }

        beforeEach(() => {
            ensureCalls = 0
            integrationsPayload = []
            useMocks({
                get: { '/api/projects/:team_id/integrations/': () => [200, { results: integrationsPayload }] },
                post: {
                    '/api/projects/:team_id/integrations/email_sandbox_sender/': () => {
                        ensureCalls += 1
                        integrationsPayload = [...integrationsPayload, SANDBOX_SENDER]
                        return [200, SANDBOX_SENDER]
                    },
                },
            })
            featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.WORKFLOWS_SANDBOX_SENDER], {
                [FEATURE_FLAGS.WORKFLOWS_SANDBOX_SENDER]: true,
            })
        })

        afterEach(() => {
            featureFlagLogic.actions.setFeatureFlags([], {})
        })

        it.each([
            {
                description: 'preselects the sandbox sender when the project has no verified own sender',
                integrations: [UNVERIFIED_OWN_SENDER, SANDBOX_SENDER],
                expectedSenderId: 7,
                expectedSenderIds: [7],
            },
            {
                description: 'prefers a verified own sender and lists the sandbox sender last',
                integrations: [SANDBOX_SENDER, VERIFIED_OWN_SENDER],
                expectedSenderId: 5,
                expectedSenderIds: [5, 7],
            },
        ])('$description', async ({ integrations, expectedSenderId, expectedSenderIds }) => {
            await loadIntegrations(integrations)

            await expectLogic(logic).toMatchValues({ senderIntegrationId: expectedSenderId })
            expect(logic.values.emailIntegrations.map((integration) => integration.id)).toEqual(expectedSenderIds)
        })

        it('lists the sandbox sender only while the flag is on, and drops a selection that is no longer listed', async () => {
            await loadIntegrations([SANDBOX_SENDER, VERIFIED_OWN_SENDER])
            logic.actions.setSenderIntegrationId(7)
            await expectLogic(logic).toMatchValues({ senderIntegrationId: 7 })

            featureFlagLogic.actions.setFeatureFlags([], {})

            await expectLogic(logic).toMatchValues({
                senderIntegrationId: 5,
                emailIntegrations: [expect.objectContaining({ id: 5 })],
            })
        })

        it('opening the modal creates a missing sandbox sender once and preselects it', async () => {
            await loadIntegrations([UNVERIFIED_OWN_SENDER])

            await expectLogic(logic, () => {
                logic.actions.setModalOpen(true)
            }).toDispatchActions(integrationsLogic, ['provisionSandboxEmailSender', 'loadIntegrationsSuccess'])
            await expectLogic(logic).toMatchValues({ senderIntegrationId: 7 })

            logic.actions.setModalOpen(false)
            await expectLogic(logic, () => {
                logic.actions.setModalOpen(true)
            }).toFinishAllListeners()
            await expectLogic(integrationsLogic).toFinishAllListeners()

            expect(ensureCalls).toBe(1)
        })

        it('does not create the sandbox sender while the flag is off, and catches up when the flag lands on an open modal', async () => {
            featureFlagLogic.actions.setFeatureFlags([], {})
            await loadIntegrations([UNVERIFIED_OWN_SENDER])

            await expectLogic(logic, () => {
                logic.actions.setModalOpen(true)
            }).toFinishAllListeners()
            await expectLogic(integrationsLogic).toFinishAllListeners()
            expect(ensureCalls).toBe(0)

            await expectLogic(logic, () => {
                featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.WORKFLOWS_SANDBOX_SENDER], {
                    [FEATURE_FLAGS.WORKFLOWS_SANDBOX_SENDER]: true,
                })
            })
                .toDispatchActions(membersLogic, ['loadAllMembersSuccess'])
                .toMatchValues({ senderIntegrationId: 7 })

            expect(ensureCalls).toBe(1)
        })

        it('sends a sandbox test without the template Reply-To, which the sandbox sender does not support', async () => {
            await loadIntegrations([SANDBOX_SENDER])
            templateLogic.actions.setTemplateValue('content.email.text', 'Hello!')
            templateLogic.actions.setTemplateValue('content.email.replyTo', 'replies@example.com')
            logic.actions.setRecipientEmail('rose.dawson@posthog.com')

            await expectLogic(logic, () => {
                logic.actions.sendTestEmail()
            }).toDispatchActions(['sendTestEmailSuccess'])

            const emailAction = capturedBody.configuration.actions.find((a: any) => a.type === 'function_email')
            expect(emailAction.config.inputs.email.value).toMatchObject({ from: { integrationId: 7 }, replyTo: '' })
        })

        it('warns about a recipient outside the organization and blocks the send while the sandbox sender is selected', async () => {
            useMocks({
                get: {
                    '/api/organizations/:organization_id/members/': {
                        results: [
                            MOCK_DEFAULT_ORGANIZATION_MEMBER,
                            MOCK_SECOND_ORGANIZATION_MEMBER,
                            {
                                ...MOCK_SECOND_ORGANIZATION_MEMBER,
                                id: 'unverified-member',
                                user: {
                                    ...MOCK_SECOND_BASIC_USER,
                                    id: 303,
                                    email: 'unverified@posthog.com',
                                    is_email_verified: false,
                                },
                            },
                        ],
                    },
                },
            })
            await loadIntegrations([SANDBOX_SENDER, VERIFIED_OWN_SENDER])
            templateLogic.actions.setTemplateValue('content.email.text', 'Hello!')

            await expectLogic(logic, () => {
                logic.actions.setModalOpen(true)
                logic.actions.setSenderIntegrationId(7)
                logic.actions.setRecipientEmail('outsider@example.com')
            })
                .toDispatchActions(membersLogic, ['loadAllMembersSuccess'])
                .toMatchValues({
                    recipientOutsideOrganization: true,
                    sendDisabledReason: 'The sandbox sender only delivers to verified members of your organization',
                    recipientSuggestions: expect.arrayContaining(['rose.dawson@posthog.com']),
                })

            logic.actions.setRecipientEmail('Rose.Dawson@posthog.com')
            await expectLogic(logic).toMatchValues({
                recipientOutsideOrganization: false,
                sendDisabledReason: undefined,
            })

            logic.actions.setRecipientEmail('unverified@posthog.com')
            await expectLogic(logic).toMatchValues({ recipientOutsideOrganization: true })
            expect(logic.values.recipientSuggestions).not.toContain('unverified@posthog.com')

            logic.actions.setRecipientEmail('outsider@example.com')
            logic.actions.setSenderIntegrationId(5)
            await expectLogic(logic).toMatchValues({
                recipientOutsideOrganization: false,
                sendDisabledReason: undefined,
            })
        })

        it('holds the send while the member list loads, and does not warn before it has loaded', async () => {
            await loadIntegrations([SANDBOX_SENDER])
            templateLogic.actions.setTemplateValue('content.email.text', 'Hello!')
            logic.actions.setRecipientEmail('outsider@example.com')

            await expectLogic(logic, () => {
                logic.actions.setModalOpen(true)
            })
                .toDispatchActions(membersLogic, ['loadAllMembers'])
                .toMatchValues({
                    recipientOutsideOrganization: false,
                    sendDisabledReason: 'Checking your organization members',
                })
                .toDispatchActions(membersLogic, ['loadAllMembersSuccess'])
                .toMatchValues({ recipientOutsideOrganization: true })
        })
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
