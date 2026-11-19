import '@testing-library/jest-dom'

import { useMocks } from '~/mocks/jest'
import type { MockResolverInfo } from '~/mocks/utils'

jest.unmock('posthog-js')

const INGESTION_HOST = 'https://ingest.example.com'

type SentEvent = { event: string; properties: Record<string, any> }

describe('send from code analytics', () => {
    const sentEvents: SentEvent[] = []
    let app: {
        posthog: typeof import('posthog-js').default
        rtl: typeof import('@testing-library/react/pure')
        Provider: typeof import('kea').Provider
        router: typeof import('kea-router').router
        initKeaTests: typeof import('~/test/init').initKeaTests
        featureFlagLogic: typeof import('lib/logic/featureFlagLogic').featureFlagLogic
        FEATURE_FLAGS: typeof import('lib/constants').FEATURE_FLAGS
        sendFromCodeGuideUrl: typeof import('./sendFromCodeGuideUrl').sendFromCodeGuideUrl
        TransactionalEmailsTable: typeof import('../TransactionalEmailsTable').TransactionalEmailsTable
    }

    beforeAll(async () => {
        jest.resetModules()
        const posthog = (await import('posthog-js')).default
        posthog.init('phc_example', {
            api_host: INGESTION_HOST,
            persistence: 'memory',
            request_batching: false,
            disable_compression: true,
            advanced_disable_flags: true,
            autocapture: false,
            capture_pageview: false,
        })
        app = {
            posthog,
            rtl: await import('@testing-library/react/pure'),
            Provider: (await import('kea')).Provider,
            router: (await import('kea-router')).router,
            initKeaTests: (await import('~/test/init')).initKeaTests,
            featureFlagLogic: (await import('lib/logic/featureFlagLogic')).featureFlagLogic,
            FEATURE_FLAGS: (await import('lib/constants')).FEATURE_FLAGS,
            sendFromCodeGuideUrl: (await import('./sendFromCodeGuideUrl')).sendFromCodeGuideUrl,
            TransactionalEmailsTable: (await import('../TransactionalEmailsTable')).TransactionalEmailsTable,
        }
    })

    afterEach(() => app.rtl.cleanup())

    const receipt = {
        id: 'template-1',
        name: 'Receipt',
        transactional_hog_flow_id: 'flow-1',
        has_draft: false,
        tags: [],
    }
    const codeEmail = {
        id: 'id-welcome',
        key: 'welcome',
        hog_flow_id: 'flow-welcome',
        description: '',
        tags: [],
        sensitive: false,
        source_url: null,
        source_origin: null,
        created_at: '2026-01-01T00:00:00Z',
        user_access_level: 'editor',
    }

    const recordSentEvents = async ({ request }: MockResolverInfo): Promise<[number, { status: number }]> => {
        sentEvents.push(...((await request.json()) as { batch: SentEvent[] }).batch)
        return [200, { status: 1 }]
    }

    it.each([
        { tab: 'a list without code sends', templates: [receipt], codeEmails: [], surfaces: ['transactional'] },
        { tab: 'a list that already sends from code', templates: [receipt], codeEmails: [codeEmail], surfaces: [] },
        { tab: 'an empty tab', templates: [], codeEmails: [], surfaces: ['transactional_empty'] },
    ])('reports a link from the domain-ready card that lands on $tab', async ({ templates, codeEmails, surfaces }) => {
        sentEvents.length = 0
        useMocks({
            get: {
                '/api/projects/:team_id/messaging_templates/': { results: templates },
                '/api/projects/:team_id/transactional_code_emails/': codeEmails,
                '/api/projects/:team_id/integrations/': { results: [] },
                '/api/projects/:team_id/tags': [],
            },
            post: { [`${INGESTION_HOST}/e/`]: recordSentEvents },
        })
        app.initKeaTests()
        app.featureFlagLogic.actions.setFeatureFlags([app.FEATURE_FLAGS.WORKFLOWS_EMAIL_FROM_CODE], {
            [app.FEATURE_FLAGS.WORKFLOWS_EMAIL_FROM_CODE]: true,
        })
        app.rtl.render(
            <app.Provider>
                <app.TransactionalEmailsTable />
            </app.Provider>
        )
        await app.rtl.screen.findByText(templates.length ? 'Receipt' : 'Send your first email from code')

        app.rtl.act(() => app.router.actions.push(app.sendFromCodeGuideUrl()))

        await app.rtl.waitFor(() => expect(app.router.values.searchParams).toEqual({}))
        app.posthog.capture('guide link test done')
        await app.rtl.waitFor(() => expect(sentEvents.map((sent) => sent.event)).toContain('guide link test done'))
        expect(
            sentEvents
                .filter(
                    (sent) => sent.event === 'send from code guide opened' && sent.properties.entry === 'domain_ready'
                )
                .map((sent) => sent.properties.surface)
        ).toEqual(surfaces)
    })

    it('reports a copied Wizard command with the command it runs', async () => {
        sentEvents.length = 0
        useMocks({
            get: {
                '/api/projects/:team_id/messaging_templates/': { results: [] },
                '/api/projects/:team_id/transactional_code_emails/': [],
                '/api/projects/:team_id/integrations/': { results: [] },
                '/api/projects/:team_id/tags': [],
            },
            post: { [`${INGESTION_HOST}/e/`]: recordSentEvents },
        })
        app.initKeaTests()
        app.featureFlagLogic.actions.setFeatureFlags(
            [app.FEATURE_FLAGS.WORKFLOWS_EMAIL_FROM_CODE, app.FEATURE_FLAGS.WORKFLOWS_TRANSACTIONAL_EMAIL_WIZARD],
            {
                [app.FEATURE_FLAGS.WORKFLOWS_EMAIL_FROM_CODE]: true,
                [app.FEATURE_FLAGS.WORKFLOWS_TRANSACTIONAL_EMAIL_WIZARD]: true,
            }
        )
        Object.defineProperty(navigator, 'clipboard', { value: { writeText: async () => {} }, configurable: true })
        app.rtl.render(
            <app.Provider>
                <app.TransactionalEmailsTable />
            </app.Provider>
        )

        app.rtl.fireEvent.click(await app.rtl.screen.findByLabelText('Copy wizard command'))

        await app.rtl.waitFor(() =>
            expect(sentEvents.map((sent) => sent.event)).toContain('wizard command copy requested')
        )
        expect(
            sentEvents
                .filter((sent) => sent.event === 'wizard command copy requested')
                .map(({ properties }) => ({ event_source: properties.event_source, command: properties.command }))
        ).toEqual([{ event_source: 'wizard_ui', command: 'email' }])
    })
})
