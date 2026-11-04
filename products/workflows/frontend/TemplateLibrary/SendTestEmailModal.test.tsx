import { MOCK_DEFAULT_ORGANIZATION_MEMBER, MOCK_DEFAULT_USER } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { userLogic } from 'scenes/userLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { messageTemplateLogic } from './messageTemplateLogic'
import { messageTemplateTestSendLogic } from './messageTemplateTestSendLogic'
import { SendTestEmailModal } from './SendTestEmailModal'

const sandbox = {
    id: 9,
    kind: 'email',
    display_name: 'Sandbox <sender@example.com>',
    config: { provider: 'sandbox', verified: true },
}

describe('SendTestEmailModal', () => {
    let logic: ReturnType<typeof messageTemplateTestSendLogic.build>
    let template: ReturnType<typeof messageTemplateLogic.build>

    beforeEach(() => {
        initKeaTests()
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.WORKFLOWS_SANDBOX_SENDER], {
            [FEATURE_FLAGS.WORKFLOWS_SANDBOX_SENDER]: true,
        })
    })
    afterEach(() => {
        cleanup()
        logic?.unmount()
        template?.unmount()
    })

    const openModal = (): void => {
        template = messageTemplateLogic({ id: 'new' })
        template.mount()
        template.actions.setTemplateValue('content.email.subject', 'Welcome')
        logic = messageTemplateTestSendLogic({ id: 'new' })
        logic.mount()
        logic.actions.setModalOpen(true)
        render(<SendTestEmailModal id="new" isOpen />)
    }

    it.each([
        [false, 'Verify your email address to send test emails to yourself.'],
        [true, null],
    ])('asks a signed-in user with verified=%s to verify their own address', async (verified, expected) => {
        useMocks({
            get: {
                '/api/projects/:team_id/integrations/': { results: [sandbox] },
                '/api/organizations/:organization_id/members/': { results: [] },
            },
        })
        userLogic.actions.loadUserSuccess({ ...MOCK_DEFAULT_USER, is_email_verified: verified })
        openModal()
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.setRecipientEmail(MOCK_DEFAULT_USER.email.toUpperCase())

        await waitFor(() =>
            expect(screen.queryByText(/isn't among the verified members you can see/) !== null).toBe(verified)
        )
        expect(
            screen.queryByText('Verify your email address to send test emails to yourself.')?.textContent ?? null
        ).toBe(expected)
    })

    it.each([
        [
            'a suggested teammate',
            'teammate@example.com',
            () => fireEvent.click(screen.getByText('teammate@example.com')),
        ],
        [
            'a typed address',
            'someone@example.com',
            (input: HTMLElement) => {
                fireEvent.change(input, { target: { value: 'someone@example.com' } })
                fireEvent.keyDown(input, { key: 'Enter' })
            },
        ],
    ])('sends the test to %s', async (_, expectedRecipient, pickRecipient) => {
        let sentTo: string | null = null
        useMocks({
            get: {
                '/api/projects/:team_id/integrations/': { results: [sandbox] },
                '/api/organizations/:organization_id/members/': {
                    results: [
                        {
                            ...MOCK_DEFAULT_ORGANIZATION_MEMBER,
                            user: {
                                ...MOCK_DEFAULT_ORGANIZATION_MEMBER.user,
                                email: 'teammate@example.com',
                                is_email_verified: true,
                            },
                        },
                    ],
                },
            },
            post: {
                '/api/environments/:team_id/hog_flows/:id/invocations/': async ({ request }: { request: Request }) => {
                    const body = await request.json()
                    const emailAction = body.configuration.actions.find((a: any) => a.type === 'function_email')
                    sentTo = emailAction.config.inputs.email.value.to.email
                    return [200, { status: 'success', nextActionId: null }]
                },
            },
        })
        openModal()
        await expectLogic(logic).toFinishAllListeners()

        const input = screen.getByPlaceholderText('you@example.com')
        fireEvent.focus(input)
        pickRecipient(input)
        fireEvent.click(screen.getByText('Send test email', { selector: 'button *' }))
        await expectLogic(logic).toFinishAllListeners()

        expect(sentTo).toBe(expectedRecipient)
    })

    it.each([true, false])('distinguishes member loading from an empty list (%s)', async (loading) => {
        let releaseMembers: () => void = () => {}
        const gate = new Promise<void>((resolve) => {
            releaseMembers = resolve
        })
        useMocks({
            get: {
                '/api/projects/:team_id/integrations/': { results: [sandbox] },
                '/api/organizations/:organization_id/members/': async () => {
                    if (loading) {
                        await gate
                    }
                    return [200, { results: [] }]
                },
            },
        })
        openModal()
        if (!loading) {
            await expectLogic(logic).toFinishAllListeners()
        }
        fireEvent.focus(screen.getByPlaceholderText('you@example.com'))
        expect(document.querySelector('.LemonSkeleton') !== null).toBe(loading)
        expect(screen.queryByText('Type an email address and press Enter') !== null).toBe(!loading)
        releaseMembers()
        await expectLogic(logic).toFinishAllListeners()
    })
})
