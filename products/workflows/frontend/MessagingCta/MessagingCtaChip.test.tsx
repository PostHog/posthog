import { MOCK_DEFAULT_USER } from 'lib/api.mock'

import userEvent from '@testing-library/user-event'

import { FEATURE_FLAGS } from 'lib/constants'

import { useMocks } from '~/mocks/jest'
import type { MockResolverInfo } from '~/mocks/utils'
import { AccessControlLevel, AccessControlResourceType, AppContext } from '~/types'

jest.unmock('posthog-js')

const INGESTION_HOST = 'https://ingest.example.com'
const CHIP = 'messaging-cta-chip-replay.player_chip'
const DAY_MS = 24 * 60 * 60 * 1000

interface Page {
    renderChip: (disabledReason?: string) => void
    chip: () => HTMLElement | null
    click: (element: HTMLElement, init?: MouseEventInit) => void
    auxClick: (element: HTMLElement, button: number) => void
    tab: () => Promise<void>
    text: (text: string) => HTMLElement | null
    sent: (event: string) => Promise<Record<string, any>[]>
    waitFor: (assertion: () => Promise<void>) => Promise<void>
    switchViewer: (uuid: string) => void
    close: () => void
}

type SentEvent = { event: string; properties: Record<string, any> }
const sentEvents: SentEvent[] = []
let pageLoads = 0

async function recordSentEvents({ request }: MockResolverInfo): Promise<[number, { status: number }]> {
    sentEvents.push(...((await request.json()) as { batch: SentEvent[] }).batch)
    return [200, { status: 1 }]
}

function setWorkflowAccess(level: AccessControlLevel): void {
    window.POSTHOG_APP_CONTEXT = {
        ...window.POSTHOG_APP_CONTEXT,
        resource_access_control: { [AccessControlResourceType.Workflow]: level },
    } as AppContext
}

function fillStorage(): void {
    let chunk = 'x'.repeat(1 << 20)
    for (let index = 0; chunk.length > 0; index++) {
        try {
            localStorage.setItem(`filler-${index}`, chunk)
        } catch {
            chunk = chunk.slice(0, chunk.length >> 1)
        }
    }
}

interface PageLoadOptions {
    sendsFromCode?: boolean
    payload?: unknown
    flagsRequest?: Promise<Record<string, string | boolean>>
}

function openFreshPageLoad(
    replayArm: string | boolean | undefined,
    { sendsFromCode = true, payload, flagsRequest }: PageLoadOptions = {}
): Page {
    let page: Page | undefined
    jest.isolateModules(() => {
        const { createElement }: typeof import('react') = require('react')
        const rtl: typeof import('@testing-library/react/pure') = require('@testing-library/react/pure')
        const posthog: typeof import('posthog-js').default = require('posthog-js').default
        const { initKeaTests }: typeof import('~/test/init') = require('~/test/init')
        const { featureFlagLogic }: typeof import('lib/logic/featureFlagLogic') = require('lib/logic/featureFlagLogic')
        const { userLogic }: typeof import('scenes/userLogic') = require('scenes/userLogic')
        const { MessagingCtaChip }: typeof import('./MessagingCtaChip') = require('./MessagingCtaChip')

        let issued = 0
        posthog.init('phc_example', {
            before_send: (event) => {
                issued++
                return event
            },
            api_host: INGESTION_HOST,
            persistence: 'memory',
            request_batching: false,
            disable_compression: true,
            advanced_disable_flags: !flagsRequest,
            autocapture: false,
            capture_pageview: false,
            ...(payload === undefined && !flagsRequest
                ? {}
                : {
                      bootstrap: {
                          featureFlags: {
                              [FEATURE_FLAGS.XPM_REPLAY_PLACEMENT]: replayArm as string,
                              [FEATURE_FLAGS.WORKFLOWS_TRANSACTIONAL_EMAIL_API]: sendsFromCode,
                          },
                          featureFlagPayloads:
                              payload === undefined ? {} : { [FEATURE_FLAGS.XPM_REPLAY_PLACEMENT]: payload as any },
                      },
                  }),
        })
        const pageLoad = ++pageLoads
        posthog.register({ test_page_load: pageLoad })
        initKeaTests()
        if (flagsRequest) {
            useMocks({
                post: {
                    [`${INGESTION_HOST}/flags/`]: async () => [
                        200,
                        { featureFlags: await flagsRequest, featureFlagPayloads: {} },
                    ],
                },
            })
        } else {
            featureFlagLogic.actions.setFeatureFlags([], {
                [FEATURE_FLAGS.WORKFLOWS_TRANSACTIONAL_EMAIL_API]: sendsFromCode,
                ...(replayArm === undefined ? {} : { [FEATURE_FLAGS.XPM_REPLAY_PLACEMENT]: replayArm }),
            })
        }
        const chip = (): HTMLElement | null => document.querySelector(`[data-attr="${CHIP}"]`)

        page = {
            renderChip: (disabledReason) => {
                rtl.cleanup()
                rtl.render(createElement(MessagingCtaChip, { placement: 'replay.player_chip', disabledReason }))
            },
            chip,
            click: (element, init) => rtl.fireEvent.click(element, init),
            auxClick: (element, button) =>
                rtl.fireEvent(element, new MouseEvent('auxclick', { bubbles: true, button })),
            tab: () => rtl.act(() => userEvent.setup({ advanceTimers: jest.advanceTimersByTime }).tab()),
            text: (text) => rtl.screen.queryByText(text),
            sent: async (event) => {
                const fromThisPage = (): SentEvent[] =>
                    sentEvents.filter((sent) => sent.properties.test_page_load === pageLoad)
                await rtl.waitFor(() => expect(fromThisPage()).toHaveLength(issued))
                return fromThisPage()
                    .filter((sent) => sent.event === event)
                    .map((sent) => sent.properties)
            },
            waitFor: (assertion) => rtl.waitFor(assertion),
            switchViewer: (uuid) => rtl.act(() => userLogic.actions.loadUserSuccess({ ...MOCK_DEFAULT_USER, uuid })),
            close: () => rtl.cleanup(),
        }
    })
    return page!
}

describe('MessagingCtaChip', () => {
    let page: Page | undefined
    let otherTab: Page | undefined

    function open(replayArm: string | boolean | undefined, options?: PageLoadOptions): Page {
        page?.close()
        page = openFreshPageLoad(replayArm, options)
        return page
    }

    beforeEach(() => {
        sentEvents.length = 0
        useMocks({ post: { [`${INGESTION_HOST}/e/`]: recordSentEvents } })
        localStorage.clear()
        setWorkflowAccess(AccessControlLevel.Editor)
    })

    afterEach(() => {
        page?.close()
        page = undefined
        otherTab?.close()
        otherTab = undefined
        jest.useRealTimers()
    })

    test.each([
        { name: 'the control arm', arm: 'control', access: AccessControlLevel.Editor, exposed: true },
        { name: 'the holdout', arm: 'holdout-1', access: AccessControlLevel.Editor, exposed: true },
        { name: 'an unset flag', arm: undefined, access: AccessControlLevel.Editor, exposed: false },
        { name: 'a false flag', arm: false, access: AccessControlLevel.Editor, exposed: false },
        { name: 'a viewer without edit access', arm: 'player_chip', access: AccessControlLevel.Viewer, exposed: false },
        {
            name: 'a team that cannot send email from code, in the chip arm',
            arm: 'player_chip',
            access: AccessControlLevel.Editor,
            exposed: false,
            sendsFromCode: false,
        },
        {
            name: 'a team that cannot send email from code, in the control arm',
            arm: 'control',
            access: AccessControlLevel.Editor,
            exposed: false,
            sendsFromCode: false,
        },
        {
            name: 'a team that cannot send email from code, in the holdout',
            arm: 'holdout-1',
            access: AccessControlLevel.Editor,
            exposed: false,
            sendsFromCode: false,
        },
    ])(
        'renders nothing for $name, and reports the arm only where the viewer is in one',
        async ({ arm, access, exposed, sendsFromCode }) => {
            setWorkflowAccess(access)
            const { renderChip, chip, sent } = open(arm, { sendsFromCode })
            renderChip()

            expect(chip()).toBeNull()
            expect(await sent('$feature_flag_called')).toEqual(
                exposed
                    ? [
                          expect.objectContaining({
                              $feature_flag: FEATURE_FLAGS.XPM_REPLAY_PLACEMENT,
                              $feature_flag_response: arm,
                          }),
                      ]
                    : []
            )
        }
    )

    it('reports its arm once, and links to email setup with clicks that share one attempt', async () => {
        const { renderChip, chip, click, auxClick, sent, switchViewer } = open('player_chip')
        renderChip()
        renderChip()

        expect(chip()?.textContent).toContain('From an email?')
        expect(await sent('$feature_flag_called')).toEqual([
            expect.objectContaining({
                $feature_flag: FEATURE_FLAGS.XPM_REPLAY_PLACEMENT,
                $feature_flag_response: 'player_chip',
            }),
        ])

        const link = chip()!.querySelector('a')!
        link.addEventListener('click', (event) => event.preventDefault())
        expect(link.getAttribute('href')).toMatch(/\/transactional\/new$/)
        const clicksAfter = async (gesture: () => void): Promise<number> => {
            gesture()
            return (await sent('message audience clicked')).length
        }
        expect([
            await clicksAfter(() => click(link)),
            await clicksAfter(() => click(link, { ctrlKey: true })),
            await clicksAfter(() => click(link, { metaKey: true })),
            await clicksAfter(() => auxClick(link, 1)),
            await clicksAfter(() => auxClick(link, 2)),
        ]).toEqual([1, 2, 3, 4, 4])
        const clicks = await sent('message audience clicked')
        expect(clicks).toEqual(
            Array(4).fill(
                expect.objectContaining({
                    source: 'replay.player_chip',
                    destination: 'send_from_code',
                    attempt_id: expect.any(String),
                })
            )
        )
        expect(new Set(clicks.map((properties) => properties.attempt_id)).size).toBe(1)

        switchViewer('ANOTHER_USER_UUID')
        click(chip()!.querySelector('a')!)
        const [, , , , nextShowing] = await sent('message audience clicked')
        expect(nextShowing.attempt_id).toEqual(expect.any(String))
        expect(nextShowing.attempt_id).not.toBe(clicks[0].attempt_id)
    })

    it("waits for this page load's flags before it shows or reports, even when the page bootstraps another arm", async () => {
        let answerFlags: (flags: Record<string, string | boolean>) => void = () => {}
        const flagsRequest = new Promise<Record<string, string | boolean>>((resolve) => {
            answerFlags = resolve
        })
        const { renderChip, chip, sent, waitFor } = open('control', { flagsRequest })
        renderChip()

        expect(chip()).toBeNull()
        expect(await sent('$feature_flag_called')).toEqual([])

        answerFlags({
            [FEATURE_FLAGS.XPM_REPLAY_PLACEMENT]: 'player_chip',
            [FEATURE_FLAGS.WORKFLOWS_TRANSACTIONAL_EMAIL_API]: true,
        })
        await waitFor(async () =>
            expect(await sent('$feature_flag_called')).toEqual([
                expect.objectContaining({
                    $feature_flag: FEATURE_FLAGS.XPM_REPLAY_PLACEMENT,
                    $feature_flag_response: 'player_chip',
                }),
            ])
        )
        expect(chip()?.textContent).toContain('From an email?')
    })

    it('shows the copy its flag payload sets', () => {
        const { renderChip, chip } = open('player_chip', { payload: { label: 'Email from PostHog?' } })
        renderChip()

        expect(chip()?.textContent).toContain('Email from PostHog?')
        expect(chip()?.textContent).not.toContain('From an email?')
    })

    it('shows its copy without a link when the host gives a reason it is disabled, and the reason on focus', async () => {
        jest.useFakeTimers()
        const { renderChip, chip, tab, text } = open('player_chip')
        renderChip('Not available here')

        expect(chip()?.textContent).toContain('From an email?')
        expect(chip()!.querySelector('a')).toBeNull()
        await tab()
        expect(text('Not available here')).not.toBeNull()
    })

    it('stays hidden for the rest of the page after its × is clicked, once storage fills after the app loaded', async () => {
        const { renderChip, chip, click, sent } = open('player_chip')
        fillStorage()
        renderChip()
        expect(chip()).not.toBeNull()

        click(chip()!.querySelector<HTMLElement>('[aria-label="Hide for 90 days"]')!)
        expect(chip()).toBeNull()
        renderChip()
        expect(chip()).toBeNull()
        expect(await sent('messaging cta dismissed')).toEqual([
            expect.objectContaining({ placement: 'replay.player_chip' }),
        ])
    })

    it('keeps a newer dismissal that another tab saved over its own', () => {
        jest.useFakeTimers({ now: new Date('2026-03-01T12:00:00Z') })
        const first = open('player_chip')
        first.renderChip()
        otherTab = openFreshPageLoad('player_chip')
        otherTab.renderChip()
        const hide = (): HTMLElement => document.querySelector<HTMLElement>('[aria-label="Hide for 90 days"]')!
        first.click(hide())

        jest.setSystemTime(Date.now() + 30 * DAY_MS)
        otherTab.click(hide())
        otherTab.close()
        otherTab = undefined

        jest.setSystemTime(Date.now() + 61 * DAY_MS)
        first.renderChip()
        expect(first.chip()).toBeNull()
    })

    it('stays hidden and silent for 90 days after its × is clicked, for that viewer only', async () => {
        jest.useFakeTimers({ now: new Date('2026-03-01T12:00:00Z') })
        const first = open('player_chip')
        first.renderChip()

        first.click(first.chip()!.querySelector<HTMLElement>('[aria-label="Hide for 90 days"]')!)
        expect(first.chip()).toBeNull()
        expect(await first.sent('messaging cta dismissed')).toEqual([
            expect.objectContaining({ placement: 'replay.player_chip' }),
        ])

        jest.setSystemTime(Date.now() + 89 * DAY_MS)
        const later = open('player_chip')
        later.renderChip()
        expect(later.chip()).toBeNull()
        expect(await later.sent('$feature_flag_called')).toEqual([])

        later.switchViewer('ANOTHER_USER_UUID')
        expect(later.chip()).not.toBeNull()

        jest.setSystemTime(Date.now() + DAY_MS)
        const afterNinetyDays = open('player_chip')
        afterNinetyDays.renderChip()
        expect(afterNinetyDays.chip()).not.toBeNull()
    })
})
