import '@testing-library/jest-dom'

import { useMocks } from '~/mocks/jest'
import type { MockResolverInfo } from '~/mocks/utils'

jest.unmock('posthog-js')

const INGESTION_HOST = 'https://ingest.example.com'
const DOMAIN = 'mail.acme.com'

type SentEvent = { event: string; properties: Record<string, any> }

describe('email domain setup started', () => {
    const sentEvents: SentEvent[] = []
    let app: {
        rtl: typeof import('@testing-library/react/pure')
        Provider: typeof import('kea').Provider
        router: typeof import('kea-router').router
        urls: typeof import('scenes/urls').urls
        initKeaTests: typeof import('~/test/init').initKeaTests
        featureFlagLogic: typeof import('lib/logic/featureFlagLogic').featureFlagLogic
        FakeEmailDomainBackend: typeof import('./__mocks__/fakeEmailDomainBackend').FakeEmailDomainBackend
        MessageChannels: typeof import('../MessageChannels').MessageChannels
        MessagingTabActions: typeof import('../../MessagingTabActions').MessagingTabActions
        SendingDomainRow: typeof import('../../Transactional/sendFromCode/SendingDomainRow').SendingDomainRow
        EmailSetupModal: typeof import('../EmailSetup/EmailSetupModal').EmailSetupModal
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
            router: (await import('kea-router')).router,
            urls: (await import('scenes/urls')).urls,
            initKeaTests: (await import('~/test/init')).initKeaTests,
            featureFlagLogic: (await import('lib/logic/featureFlagLogic')).featureFlagLogic,
            FakeEmailDomainBackend: (await import('./__mocks__/fakeEmailDomainBackend')).FakeEmailDomainBackend,
            MessageChannels: (await import('../MessageChannels')).MessageChannels,
            MessagingTabActions: (await import('../../MessagingTabActions')).MessagingTabActions,
            SendingDomainRow: (await import('../../Transactional/sendFromCode/SendingDomainRow')).SendingDomainRow,
            EmailSetupModal: (await import('../EmailSetup/EmailSetupModal')).EmailSetupModal,
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
    ])('sends one start event with the entry for $from', async ({ seed, ui, presses, entry }) => {
        sentEvents.length = 0
        const backend = new app.FakeEmailDomainBackend()
        if (seed === 'verified') {
            backend.addSender({ email: `hello@${DOMAIN}`, verified: true })
            backend.verifyDomain(DOMAIN)
        } else if (seed === 'unverified') {
            backend.addSender({ email: `hello@${DOMAIN}` })
        }
        const mocks = backend.mocks()
        useMocks({
            ...mocks,
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
