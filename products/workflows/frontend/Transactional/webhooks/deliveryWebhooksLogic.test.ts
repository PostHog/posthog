import { expectLogic } from 'kea-test-utils'

import { lemonToast } from '@posthog/lemon-ui'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { DELIVERY_WEBHOOK_LIST_FILTER_GROUPS } from './deliveryWebhookPayload'
import { deliveryWebhooksLogic } from './deliveryWebhooksLogic'

describe('deliveryWebhooksLogic', () => {
    let logic: ReturnType<typeof deliveryWebhooksLogic.build>
    let created: Record<string, any>[]

    beforeEach(() => {
        created = []
        useMocks({
            post: {
                '/api/projects/:team_id/hog_functions/': async ({ request }) => {
                    const body = (await request.json()) as Record<string, any>
                    created.push(body)
                    return [201, { id: 'new-webhook', ...body }]
                },
            },
        })
        initKeaTests()
        logic = deliveryWebhooksLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    it('creates a signed webhook that the webhooks list finds, and shows its secret once', async () => {
        logic.actions.openAddModal()
        logic.actions.setWebhookFormValues({
            url: ' https://example.com/hooks/prod ',
            events: ['$workflows_email_delivered', '$workflows_email_bounced'],
        })
        logic.actions.submitWebhookForm()
        await expectLogic(logic).toFinishAllListeners()

        expect(created).toHaveLength(1)
        const [webhook] = created
        expect(webhook.template_id).toEqual('template-webhook')
        expect(webhook.inputs.url.value).toEqual('https://example.com/hooks/prod')
        // Two webhooks on one host stay apart in the list.
        expect(webhook.name).toEqual('Transactional email webhook: example.com/hooks/prod')
        expect(webhook.filters.events.map((e: { id: string }) => e.id)).toEqual([
            '$workflows_email_delivered',
            '$workflows_email_bounced',
        ])
        // The list asks the API for destinations whose filters contain this group.
        expect(webhook.filters.properties).toEqual(
            expect.arrayContaining(DELIVERY_WEBHOOK_LIST_FILTER_GROUPS[0].properties!)
        )

        const secret = logic.values.createdSecret
        expect(webhook.inputs.signing_secret.value).toEqual(secret)
        expect(secret).toMatch(/^whsec_/)
        expect(atob(secret!.slice('whsec_'.length))).toHaveLength(32)

        logic.actions.closeAddModal()
        expect(logic.values.createdSecret).toBeNull()
    })

    it.each([
        ['a URL without a scheme', { url: 'example.com/hooks' }],
        ['a plain http URL', { url: 'http://example.com/hooks' }],
        ['no events', { url: 'https://example.com/hooks', events: [] }],
    ])('does not create a webhook with %s, and shows only the field error', async (_, values) => {
        const toastError = jest.spyOn(lemonToast, 'error')
        logic.actions.setWebhookFormValues(values)
        logic.actions.submitWebhookForm()
        await expectLogic(logic).toFinishAllListeners()

        expect(created).toHaveLength(0)
        expect(logic.values.createdSecret).toBeNull()
        expect(toastError).not.toHaveBeenCalled()
    })
})
