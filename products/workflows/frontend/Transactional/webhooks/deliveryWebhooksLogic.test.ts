import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { hogFunctionsListLogic } from 'scenes/hog-functions/list/hogFunctionsListLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { DELIVERY_WEBHOOK_LIST_PROPS, deliveryWebhooksLogic } from './deliveryWebhooksLogic'

const jsonbContains = (value: any, part: any): boolean => {
    if (Array.isArray(part)) {
        return Array.isArray(value) && part.every((item) => value.some((candidate) => jsonbContains(candidate, item)))
    }
    if (part !== null && typeof part === 'object') {
        return (
            value !== null &&
            typeof value === 'object' &&
            Object.entries(part).every(([key, item]) => jsonbContains(value[key], item))
        )
    }
    return value === part
}

const HAND_BUILT_WEBHOOK = {
    id: 'hand-built',
    name: 'Every pageview',
    type: 'destination',
    filters: { events: [{ id: '$pageview', type: 'events' }] },
}

const SERVER_PAGE_SIZE = 2

const STORED_TEMPLATES = [
    { id: '0190e3a1-aaaa-7000-8000-00000000abcd', name: 'Receipt', transactional_hog_flow_id: 'flow-receipt' },
    { id: 'template-newsletter', name: 'Newsletter', transactional_hog_flow_id: null },
    { id: 'template-reset', name: 'Password reset', transactional_hog_flow_id: 'flow-reset' },
    { id: '0190e3a1-aaaa-7000-8000-00000000ef01', name: 'Receipt', transactional_hog_flow_id: 'flow-receipt-copy' },
]

describe('deliveryWebhooksLogic', () => {
    let logic: ReturnType<typeof deliveryWebhooksLogic.build>
    let created: Record<string, any>[]
    let requestedTeamIds: Set<string>
    const environment = { ...MOCK_DEFAULT_TEAM, id: 2001 }

    beforeEach(() => {
        created = []
        requestedTeamIds = new Set()
        useMocks({
            get: {
                '/api/projects/:team_id/messaging_templates/': ({ request, params }) => {
                    requestedTeamIds.add(String(params.team_id))
                    const query = new URL(request.url).searchParams
                    const matching = STORED_TEMPLATES.filter(
                        (template) => query.get('transactional') !== 'true' || template.transactional_hog_flow_id
                    )
                    const offset = Number(query.get('offset') ?? 0)
                    const limit = Math.min(Number(query.get('limit') ?? 100), SERVER_PAGE_SIZE)
                    return [200, { count: matching.length, results: matching.slice(offset, offset + limit) }]
                },
                '/api/environments/:team_id/hog_functions/': ({ request }) => {
                    const groups = JSON.parse(new URL(request.url).searchParams.get('filter_groups') ?? '[]')
                    const results = [HAND_BUILT_WEBHOOK, ...created].filter(
                        (destination) =>
                            groups.length === 0 ||
                            groups.some((group: Record<string, any>) => jsonbContains(destination.filters, group))
                    )
                    return [200, { count: results.length, next: null, results }]
                },
            },
            post: {
                '/api/projects/:team_id/hog_functions/': async ({ request, params }) => {
                    requestedTeamIds.add(String(params.team_id))
                    const body = (await request.json()) as Record<string, any>
                    created.push({ id: 'new-webhook', ...body })
                    return [201, { id: 'new-webhook', ...body }]
                },
            },
        })
        initKeaTests(true, environment)
        logic = deliveryWebhooksLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    it.each<[string, string[], string[] | undefined]>([
        ['every transactional email', [], undefined],
        ['the picked transactional emails', ['Password reset'], ['flow-reset']],
    ])('creates a signed webhook for %s that the webhooks list finds', async (_, picked, workflowIds) => {
        const list = hogFunctionsListLogic(DELIVERY_WEBHOOK_LIST_PROPS)
        list.mount()
        logic.actions.openAddModal()
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.transactionalEmailOptions.map(({ label }) => label)).toEqual([
            'Receipt (0000abcd)',
            'Password reset',
            'Receipt (0000ef01)',
        ])
        logic.actions.setWebhookFormValues({
            url: ' https://example.com/hooks/prod ',
            events: ['$workflows_email_delivered', '$workflows_email_bounced'],
            workflowIds: logic.values.transactionalEmailOptions
                .filter(({ label }) => picked.includes(label))
                .map(({ key }) => key),
        })
        logic.actions.submitWebhookForm()
        await expectLogic(logic).toFinishAllListeners()

        expect(created).toHaveLength(1)
        expect([...requestedTeamIds]).toEqual([String(environment.id)])
        const [webhook] = created
        expect(webhook.template_id).toEqual('template-webhook')
        expect(webhook.inputs.url.value).toEqual('https://example.com/hooks/prod')
        expect(webhook.name).toEqual('Transactional email webhook: example.com/hooks/prod')
        expect(webhook.filters.events.map((e: { id: string }) => e.id)).toEqual([
            '$workflows_email_delivered',
            '$workflows_email_bounced',
        ])
        await expectLogic(list).toFinishAllListeners()
        expect(list.values.hogFunctions.map(({ id }) => id)).toEqual(['new-webhook'])
        expect(webhook.filters.properties.find((p: { key: string }) => p.key === '$workflow_id')?.value).toEqual(
            workflowIds
        )

        const secret = logic.values.createdSecret
        expect(webhook.inputs.signing_secret.value).toEqual(secret)
        expect(secret).toMatch(/^whsec_/)
        expect(atob(secret!.slice('whsec_'.length))).toHaveLength(32)

        logic.actions.closeAddModal()
        expect(logic.values.createdSecret).toBeNull()
        list.unmount()
    })

    it('names a webhook with a long path by its host and the start of the path', async () => {
        logic.actions.setWebhookFormValues({ url: `https://example.com/${'a'.repeat(500)}` })
        logic.actions.submitWebhookForm()
        await expectLogic(logic).toFinishAllListeners()

        expect(created[0].name).toEqual(`Transactional email webhook: example.com/${'a'.repeat(29)}…`)
        expect(created[0].inputs.url.value).toEqual(`https://example.com/${'a'.repeat(500)}`)
    })

    it.each([
        ['a URL without a scheme', { url: 'example.com/hooks' }],
        ['a plain http URL', { url: 'http://example.com/hooks' }],
        ['no events', { url: 'https://example.com/hooks', events: [] }],
    ])('does not create a webhook with %s', async (_, values) => {
        logic.actions.setWebhookFormValues(values)
        logic.actions.submitWebhookForm()
        await expectLogic(logic).toFinishAllListeners()

        expect(created).toHaveLength(0)
        expect(logic.values.createdSecret).toBeNull()
    })
})
