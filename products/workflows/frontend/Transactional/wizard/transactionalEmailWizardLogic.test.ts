import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { removeProjectIdIfPresent } from 'lib/utils/kea-router'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { transactionalEmailWizardLogic } from './transactionalEmailWizardLogic'

jest.mock('lib/lemon-ui/LemonToast', () => ({ lemonToast: { success: jest.fn(), error: jest.fn() } }))

describe('transactionalEmailWizardLogic', () => {
    let logic: ReturnType<typeof transactionalEmailWizardLogic.build>
    let createTemplate: jest.Mock
    let createTemplateBody: Record<string, any> | undefined
    let makeTransactional: jest.Mock

    beforeEach(() => {
        createTemplate = jest.fn(async ({ request }) => {
            createTemplateBody = await request.json()
            return [201, { id: 'created-id' }]
        })
        makeTransactional = jest.fn(() => [200, { id: 'created-id', transactional_hog_flow_id: 'flow-id' }])
        useMocks({
            get: {
                '/api/environments/:team_id/integrations/': {
                    results: [
                        {
                            id: 7,
                            kind: 'email',
                            config: { email: 'no-reply@example.com', domain: 'example.com', verified: true },
                        },
                    ],
                },
            },
            post: {
                '/api/projects/:team_id/messaging_templates/': createTemplate,
                '/api/projects/:team_id/messaging_templates/:id/make_transactional/': makeTransactional,
            },
        })
        initKeaTests()
        router.actions.push('/transactional/new')
        logic = transactionalEmailWizardLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    test.each([
        ['an email missing its sender is not created', {}, 0, 'sender', '/transactional/new'],
        [
            'a complete email is created, made transactional, and opened in its section',
            { from: { integrationId: 7 }, subject: 'Reset your password' },
            1,
            'name',
            '/transactional/library/templates/created-id',
        ],
    ])('%s', async (_, emailPatch, expectedCalls, expectedStep, expectedPath) => {
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.updateDraft({ name: 'Password reset' })
        logic.actions.updateEmail(emailPatch)

        await expectLogic(logic, () => logic.actions.createTransactionalEmail()).toFinishAllListeners()

        expect(createTemplate).toHaveBeenCalledTimes(expectedCalls)
        expect(makeTransactional).toHaveBeenCalledTimes(expectedCalls)
        expect(removeProjectIdIfPresent(router.values.location.pathname)).toEqual(expectedPath)
        expect(logic.values.currentStep).toEqual(expectedStep)
    })

    it('leaves out the design that a text-only template clears, since the API rejects a null design', async () => {
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.updateDraft({ name: 'Plain receipt' })
        logic.actions.updateEmail({
            from: { integrationId: 7 },
            subject: 'Your receipt',
            text: 'Thanks for your order.',
            html: '',
            design: null,
        })

        await expectLogic(logic, () => logic.actions.createTransactionalEmail()).toFinishAllListeners()

        expect(createTemplateBody?.content.email).toEqual(expect.objectContaining({ text: 'Thanks for your order.' }))
        expect(createTemplateBody?.content.email).not.toHaveProperty('design')
    })
})
