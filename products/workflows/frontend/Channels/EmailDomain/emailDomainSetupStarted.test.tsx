import '@testing-library/jest-dom'

import { useMocks } from '~/mocks/jest'
import type { MockResolverInfo } from '~/mocks/utils'

import type { HogFlow } from '../../Workflows/hogflows/types'

jest.unmock('posthog-js')

const INGESTION_HOST = 'https://ingest.example.com'
const DOMAIN = 'mail.acme.com'

type SentEvent = { event: string; properties: Record<string, any> }

const TEAM_ID = 997

const LIVE_ON_TEST_SENDER: HogFlow = {
    id: '0193a1b2-c3d4-7e5f-8a9b-0c1d2e3f4a5b',
    name: 'Welcome',
    version: 1,
    status: 'active',
    team_id: TEAM_ID,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    exit_condition: 'exit_only_at_end',
    conversion: { filters: [] },
    actions: [
        {
            id: 'trigger_node',
            type: 'trigger',
            name: 'Trigger',
            description: '',
            created_at: 0,
            updated_at: 0,
            config: { type: 'event', filters: { events: [{ id: '$pageview', type: 'events' }] } },
        },
        {
            id: 'email',
            type: 'email_sandbox',
            name: 'Email',
            description: '',
            created_at: 0,
            updated_at: 0,
            config: {
                inputs: {
                    email: {
                        templating: 'liquid',
                        value: { to: { email: '{{ person.properties.email }}' }, subject: 'Hi', html: '<p>Hi</p>' },
                    },
                },
            },
        },
    ],
    edges: [{ from: 'trigger_node', to: 'email', type: 'continue' }],
}

const STORED_WORKFLOWS: Record<string, HogFlow> = {
    [LIVE_ON_TEST_SENDER.id]: LIVE_ON_TEST_SENDER,
}

describe('email domain setup started', () => {
    const sentEvents: SentEvent[] = []
    let app: {
        rtl: typeof import('@testing-library/react/pure')
        Provider: typeof import('kea').Provider
        BindLogic: typeof import('kea').BindLogic
        router: typeof import('kea-router').router
        urls: typeof import('scenes/urls').urls
        initKeaTests: typeof import('~/test/init').initKeaTests
        featureFlagLogic: typeof import('lib/logic/featureFlagLogic').featureFlagLogic
        FakeEmailDomainBackend: typeof import('./__mocks__/fakeEmailDomainBackend').FakeEmailDomainBackend
        MessageChannels: typeof import('../MessageChannels').MessageChannels
        MessagingTabActions: typeof import('../../MessagingTabActions').MessagingTabActions
        SendingDomainRow: typeof import('../../Transactional/sendFromCode/SendingDomainRow').SendingDomainRow
        EmailSetupModal: typeof import('../EmailSetup/EmailSetupModal').EmailSetupModal
        workflowLogic: typeof import('../../Workflows/workflowLogic').workflowLogic
        WorkflowSandboxSenderBanner: typeof import('../../Workflows/WorkflowSandboxSenderBanner').WorkflowSandboxSenderBanner
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
            rtl: await import('@testing-library/react/pure'),
            Provider: (await import('kea')).Provider,
            BindLogic: (await import('kea')).BindLogic,
            router: (await import('kea-router')).router,
            urls: (await import('scenes/urls')).urls,
            initKeaTests: (await import('~/test/init')).initKeaTests,
            featureFlagLogic: (await import('lib/logic/featureFlagLogic')).featureFlagLogic,
            FakeEmailDomainBackend: (await import('./__mocks__/fakeEmailDomainBackend')).FakeEmailDomainBackend,
            MessageChannels: (await import('../MessageChannels')).MessageChannels,
            MessagingTabActions: (await import('../../MessagingTabActions')).MessagingTabActions,
            SendingDomainRow: (await import('../../Transactional/sendFromCode/SendingDomainRow')).SendingDomainRow,
            EmailSetupModal: (await import('../EmailSetup/EmailSetupModal')).EmailSetupModal,
            workflowLogic: (await import('../../Workflows/workflowLogic')).workflowLogic,
            WorkflowSandboxSenderBanner: (await import('../../Workflows/WorkflowSandboxSenderBanner'))
                .WorkflowSandboxSenderBanner,
        }
    })

    afterEach(() => app.rtl.cleanup())

    const press = async (target: string): Promise<void> => {
        const found = await app.rtl.waitFor(() => {
            const element =
                document.querySelector<HTMLElement>(`[data-attr="${target}"]`) ?? app.rtl.screen.queryByText(target)
            expect(element).not.toBeNull()
            return element as HTMLElement
        })
        app.rtl.fireEvent.click(found)
    }

    it.each([
        {
            from: 'the email card in the channel catalog',
            seed: 'none',
            ui: () => <app.MessageChannels />,
            presses: ['workflows-channel-catalog-connect-email'],
            entry: 'channels',
        },
        {
            from: 'the new channel menu in the header',
            seed: 'none',
            ui: () => <app.MessagingTabActions tab="channels" channelsUrl={app.urls.workflows('channels')} />,
            presses: ['new-channel-button', 'Email'],
            entry: 'channels',
        },
        {
            from: 'the transactional sending domain row',
            seed: 'none',
            ui: () => <app.SendingDomainRow />,
            presses: ['send-from-code-set-up-domain'],
            entry: 'transactional',
        },
        {
            from: 'a new domain picked while adding a sender',
            seed: 'verified',
            ui: () => <app.MessageChannels />,
            presses: ['workflows-channel-catalog-connect-email', 'email-sender-add-new-domain'],
            entry: 'add_sender',
        },
        {
            from: 'configure on an unverified sender',
            seed: 'unverified',
            ui: () => <app.MessageChannels />,
            presses: [DOMAIN, 'Configure'],
            entry: 'configure',
        },
        {
            from: 'the broadcast sender modal',
            seed: 'none',
            ui: () => <app.EmailSetupModal entry="broadcast" onClose={jest.fn()} onComplete={jest.fn()} />,
            presses: [],
            entry: 'broadcast',
        },
        {
            from: 'the repair button on a live workflow whose senders stopped',
            seed: 'stopped',
            ui: () => (
                <app.BindLogic logic={app.workflowLogic} props={{ id: LIVE_ON_TEST_SENDER.id }}>
                    <app.WorkflowSandboxSenderBanner id={LIVE_ON_TEST_SENDER.id} />
                </app.BindLogic>
            ),
            presses: ['workflow-sandbox-sender-fix-domain'],
            entry: 'sandbox_sender_banner_repair',
        },
    ])('sends one start event with the entry for $from', async ({ seed, ui, presses, entry }) => {
        sentEvents.length = 0
        const backend = new app.FakeEmailDomainBackend()
        if (seed === 'verified') {
            backend.addSender({ email: `hello@${DOMAIN}`, verified: true })
            backend.verifyDomain(DOMAIN)
        } else if (seed === 'unverified') {
            backend.addSender({ email: `hello@${DOMAIN}` })
        } else if (seed === 'stopped') {
            backend.addSender({ email: `hello@${DOMAIN}` })
            backend.stopsSending(DOMAIN)
        }
        const mocks = backend.mocks()
        useMocks({
            ...mocks,
            get: {
                ...mocks.get,
                '/api/projects/:team_id/hog_flows/:id/': ({ params }: MockResolverInfo) =>
                    params.team_id === String(TEAM_ID) && STORED_WORKFLOWS[params.id as string]
                        ? [200, STORED_WORKFLOWS[params.id as string]]
                        : [404, { detail: 'Not found.' }],
            },
            post: {
                ...mocks.post,
                [`${INGESTION_HOST}/e/`]: async ({ request }: MockResolverInfo) => {
                    sentEvents.push(...((await request.json()) as { batch: SentEvent[] }).batch)
                    return [200, { status: 1 }]
                },
            },
        })
        app.initKeaTests()
        app.featureFlagLogic.mount()
        app.router.actions.push(app.urls.workflows('channels'))
        app.rtl.render(<app.Provider>{ui()}</app.Provider>)

        for (const target of presses) {
            await press(target)
        }

        await app.rtl.waitFor(() =>
            expect(
                sentEvents
                    .filter((sent) => sent.event === 'email domain setup started')
                    .map((sent) => sent.properties.entry)
            ).toEqual([entry])
        )
    })
})
