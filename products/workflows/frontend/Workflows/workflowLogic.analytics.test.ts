import { useMocks } from '~/mocks/jest'
import { MockResolverInfo } from '~/mocks/utils'

import type { HogFlow } from './hogflows/types'

jest.unmock('posthog-js')

const INGESTION_HOST = 'https://ingest.example.com'

describe('workflowLogic analytics', () => {
    const sentEvents: { event: string; properties: Record<string, any> }[] = []
    let posthog: typeof import('posthog-js').default
    let initKeaTests: typeof import('~/test/init').initKeaTests
    let expectLogic: typeof import('kea-test-utils').expectLogic
    let workflowLogic: typeof import('./workflowLogic').workflowLogic
    let emailPrefill: typeof import('./workflowEmailPrefill')

    beforeAll(async () => {
        // posthog-js keeps the fetch it finds at import, so a fresh copy has to load after this ingestion fake.
        const mockedApi = globalThis.fetch
        globalThis.fetch = (async (url: RequestInfo | URL, init?: RequestInit) => {
            if (!String(url).startsWith(INGESTION_HOST)) {
                return mockedApi(url, init)
            }
            sentEvents.push(...JSON.parse(String(init?.body)).batch)
            return new Response('{"status":1}', { status: 200 })
        }) as typeof fetch
        jest.resetModules()
        posthog = (await import('posthog-js')).default
        initKeaTests = (await import('~/test/init')).initKeaTests
        expectLogic = (await import('kea-test-utils')).expectLogic
        workflowLogic = (await import('./workflowLogic')).workflowLogic
        emailPrefill = await import('./workflowEmailPrefill')
    })

    beforeEach(() => {
        posthog.init('phc_example', {
            api_host: INGESTION_HOST,
            persistence: 'memory',
            request_batching: false,
            disable_compression: true,
            advanced_disable_flags: true,
            autocapture: false,
            capture_pageview: false,
        })
        initKeaTests()
    })

    it.each([
        { case: 'an untouched email', act: null, applied: true, skipped_reason: null },
        { case: 'a typed subject', act: 'type', applied: false, skipped_reason: 'edited' },
        { case: 'a saved workflow', act: 'save', applied: false, skipped_reason: 'saved' },
    ] as const)('reports an AI email draft that meets $case', async ({ case: _, act, ...expected }) => {
        let respond: (body: unknown) => void = () => {}
        const draft = new Promise((resolve) => {
            respond = resolve
        })
        useMocks({
            post: {
                '/api/projects/:team_id/workflow_email_drafts/': () => draft.then((body) => [200, body]),
                '/api/environments/:team_id/hog_flows/': async ({ request }: MockResolverInfo) => [
                    201,
                    { ...((await request.json()) as HogFlow), id: 'wf-created' },
                ],
            },
        })
        const logic = workflowLogic({
            id: 'new',
            triggerPrefill: JSON.stringify({
                type: 'event',
                filters: { events: [{ id: 'signed_up', type: 'events' }] },
            }),
            emailPrefill: JSON.stringify({ subject: 'Template subject', paragraphs: ['Template body'] }),
            draftSource: JSON.stringify({ source: 'error_tracking', source_id: 'issue-1' }),
        })
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadWorkflowSuccess', 'loadAiEmailDraft'])
        if (act === 'type') {
            const typed = { subject: 'Typed by me', paragraphs: ['Template body'] }
            logic.actions.setWorkflowValue(
                'actions',
                emailPrefill.withPrefilledEmail(logic.values.workflow, typed).actions
            )
        } else if (act === 'save') {
            await expectLogic(logic, () => logic.actions.saveWorkflow(logic.values.workflow)).toDispatchActions([
                'saveWorkflowSuccess',
            ])
        }
        sentEvents.length = 0

        respond({ subject: 'Written by AI', preheader: '', html: '<p>AI</p>', text: 'AI', generated_by: 'ai' })
        await expectLogic(logic).toDispatchActions(['loadAiEmailDraftSuccess']).toFinishAllListeners()

        expect(sentEvents.filter(({ event }) => event === 'email draft prefilled').map((e) => e.properties)).toEqual([
            expect.objectContaining({
                surface: 'workflow',
                source: 'error_tracking',
                generated_by: 'ai',
                ...expected,
            }),
        ])
    })
})
