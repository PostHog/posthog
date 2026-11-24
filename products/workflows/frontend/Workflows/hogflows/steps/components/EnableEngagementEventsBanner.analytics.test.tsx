import '@testing-library/jest-dom'

import { useMocks } from '~/mocks/jest'
import type { MockResolverInfo } from '~/mocks/utils'

jest.unmock('posthog-js')

const INGESTION_HOST = 'https://ingest.example.com'

type SentEvent = { event: string; properties: Record<string, any> }

describe('engagement events banner restricted area event', () => {
    const sentEvents: SentEvent[] = []
    let app: {
        posthog: typeof import('posthog-js').default
        rtl: typeof import('@testing-library/react/pure')
        Provider: typeof import('kea').Provider
        BindLogic: typeof import('kea').BindLogic
        initKeaTests: typeof import('~/test/init').initKeaTests
        expectLogic: typeof import('kea-test-utils').expectLogic
        MOCK_DEFAULT_TEAM: typeof import('lib/api.mock').MOCK_DEFAULT_TEAM
        OrganizationMembershipLevel: typeof import('lib/constants').OrganizationMembershipLevel
        workflowLogic: typeof import('../../../workflowLogic').workflowLogic
        HogFlowFunctionConfiguration: typeof import('./HogFlowFunctionConfiguration').HogFlowFunctionConfiguration
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
            BindLogic: (await import('kea')).BindLogic,
            initKeaTests: (await import('~/test/init')).initKeaTests,
            expectLogic: (await import('kea-test-utils')).expectLogic,
            MOCK_DEFAULT_TEAM: (await import('lib/api.mock')).MOCK_DEFAULT_TEAM,
            OrganizationMembershipLevel: (await import('lib/constants')).OrganizationMembershipLevel,
            workflowLogic: (await import('../../../workflowLogic')).workflowLogic,
            HogFlowFunctionConfiguration: (await import('./HogFlowFunctionConfiguration')).HogFlowFunctionConfiguration,
        }
    })

    afterEach(() => app.rtl.cleanup())

    it.each([
        {
            when: 'engagement capture is off and the banner shows',
            captureOn: false,
            shownText: 'Enable engagement events',
            expectedEvents: 1,
        },
        {
            when: 'engagement capture is already on',
            captureOn: true,
            shownText: 'Email engagement is being captured as PostHog events.',
            expectedEvents: 0,
        },
    ])(
        'sends $expectedEvents project restricted area events to a project member when $when',
        async ({ captureOn, shownText, expectedEvents }) => {
            sentEvents.length = 0
            const receivedBodies: Promise<void>[] = []
            useMocks({
                get: {
                    '/api/projects/:team_id/hog_function_templates': {
                        results: [{ id: 'template-email', name: 'Email', type: 'destination', inputs_schema: [] }],
                        count: 1,
                    },
                },
                post: {
                    [`${INGESTION_HOST}/e/`]: async ({ request }: MockResolverInfo) => {
                        const body = request.json().then((parsed) => {
                            sentEvents.push(...(parsed as { batch: SentEvent[] }).batch)
                        })
                        receivedBodies.push(body)
                        await body
                        return [200, { status: 1 }]
                    },
                },
            })
            app.initKeaTests(true, {
                ...app.MOCK_DEFAULT_TEAM,
                effective_membership_level: app.OrganizationMembershipLevel.Member,
                workflows_config: {
                    ...app.MOCK_DEFAULT_TEAM.workflows_config,
                    capture_workflows_engagement_events: captureOn,
                },
            })
            // The panel shows a spinner while the editor loads its templates, which remounts the banner. A
            // person opens a step only after the editor has loaded, so the test lets every load finish first.
            // Reading the templates starts the lazy load from a zero-delay timer. A second zero-delay timer
            // runs after it, so the lazy load is running before the test waits for the listeners.
            const editor = app.workflowLogic({ id: 'new' })
            editor.mount()
            void editor.values.hogFunctionTemplatesById
            await new Promise((resolve) => setTimeout(resolve, 0))
            await app.expectLogic(editor).toFinishAllListeners()

            app.rtl.render(
                <app.Provider>
                    <app.BindLogic logic={app.workflowLogic} props={{ id: 'new' }}>
                        <app.HogFlowFunctionConfiguration
                            templateId="template-email"
                            inputs={{}}
                            setInputs={() => {}}
                        />
                    </app.BindLogic>
                </app.Provider>
            )
            await app.rtl.screen.findByText(shownText)

            app.posthog.capture('engagement banner test done')
            await app.rtl.waitFor(() =>
                expect(sentEvents.map((sent) => sent.event)).toContain('engagement banner test done')
            )
            // Each event is its own request, so the marker can be parsed before an earlier event is.
            await Promise.all(receivedBodies)
            expect(
                sentEvents.filter(
                    (sent) => sent.event === 'restricted_area_accessed' && sent.properties.scope === 'project'
                )
            ).toHaveLength(expectedEvents)
        }
    )
})
