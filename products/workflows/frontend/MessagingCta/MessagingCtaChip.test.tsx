import { MOCK_DEFAULT_USER } from 'lib/api.mock'

import userEvent from '@testing-library/user-event'

import { FEATURE_FLAGS } from 'lib/constants'

import { AccessControlLevel, AccessControlResourceType, AppContext } from '~/types'

const CHIP = 'messaging-cta-chip-replay.player_chip'
const DAY_MS = 24 * 60 * 60 * 1000

interface Page {
    renderChip: (disabledReason?: string) => void
    chip: () => HTMLElement | null
    click: (element: HTMLElement, init?: MouseEventInit) => void
    auxClick: (element: HTMLElement, button: number) => void
    tab: () => Promise<void>
    text: (text: string) => HTMLElement | null
    captured: (event: string) => Record<string, unknown>[]
    switchViewer: (uuid: string) => void
    close: () => void
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

function openFreshPageLoad(replayArm: string | boolean | undefined, sendsFromCode: boolean): Page {
    let page: Page | undefined
    jest.isolateModules(() => {
        const { createElement }: typeof import('react') = require('react')
        const rtl: typeof import('@testing-library/react/pure') = require('@testing-library/react/pure')
        const posthog: typeof import('posthog-js').default = require('posthog-js').default
        const { initKeaTests }: typeof import('~/test/init') = require('~/test/init')
        const { featureFlagLogic }: typeof import('lib/logic/featureFlagLogic') = require('lib/logic/featureFlagLogic')
        const { userLogic }: typeof import('scenes/userLogic') = require('scenes/userLogic')
        const { MessagingCtaChip }: typeof import('./MessagingCtaChip') = require('./MessagingCtaChip')

        initKeaTests()
        const capture = jest.spyOn(posthog, 'capture').mockImplementation(() => undefined)
        featureFlagLogic.actions.setFeatureFlags([], {
            [FEATURE_FLAGS.WORKFLOWS_TRANSACTIONAL_EMAIL_API]: sendsFromCode,
            ...(replayArm === undefined ? {} : { [FEATURE_FLAGS.XPM_REPLAY_PLACEMENT]: replayArm }),
        })
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
            tab: () => userEvent.tab(),
            text: (text) => rtl.screen.queryByText(text),
            captured: (event) =>
                capture.mock.calls.filter(([name]) => name === event).map(([, properties]) => properties ?? {}),
            switchViewer: (uuid) => rtl.act(() => userLogic.actions.loadUserSuccess({ ...MOCK_DEFAULT_USER, uuid })),
            close: () => {
                rtl.cleanup()
                capture.mockRestore()
            },
        }
    })
    return page!
}

describe('MessagingCtaChip', () => {
    let page: Page | undefined
    let otherTab: Page | undefined

    function open(replayArm: string | boolean | undefined, sendsFromCode = true): Page {
        page?.close()
        page = openFreshPageLoad(replayArm, sendsFromCode)
        return page
    }

    beforeEach(() => {
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
        ({ arm, access, exposed, sendsFromCode }) => {
            setWorkflowAccess(access)
            const { renderChip, chip, captured } = open(arm, sendsFromCode)
            renderChip()

            expect(chip()).toBeNull()
            expect(captured('$feature_flag_called')).toEqual(
                exposed ? [{ $feature_flag: FEATURE_FLAGS.XPM_REPLAY_PLACEMENT, $feature_flag_response: arm }] : []
            )
        }
    )

    it('reports its arm once, and links to email setup with clicks that each carry a new attempt', () => {
        const { renderChip, chip, click, auxClick, captured } = open('player_chip')
        renderChip()
        renderChip()

        expect(chip()?.textContent).toContain('From an email?')
        expect(captured('$feature_flag_called')).toEqual([
            { $feature_flag: FEATURE_FLAGS.XPM_REPLAY_PLACEMENT, $feature_flag_response: 'player_chip' },
        ])

        const link = chip()!.querySelector('a')!
        expect(link.getAttribute('href')).toMatch(/\/transactional\/new$/)
        const clicksAfter = (gesture: () => void): number => {
            gesture()
            return captured('message audience clicked').length
        }
        expect([
            clicksAfter(() => click(link)),
            clicksAfter(() => click(link, { ctrlKey: true })),
            clicksAfter(() => click(link, { metaKey: true })),
            clicksAfter(() => auxClick(link, 1)),
            clicksAfter(() => auxClick(link, 2)),
        ]).toEqual([1, 2, 3, 4, 4])
        const clicks = captured('message audience clicked')
        expect(clicks).toEqual(
            Array(4).fill({
                source: 'replay.player_chip',
                destination: 'send_from_code',
                attempt_id: expect.any(String),
            })
        )
        expect(new Set(clicks.map((properties) => properties.attempt_id)).size).toBe(4)
    })

    it('shows its copy without a link when the host gives a reason it is disabled, and the reason on focus', async () => {
        const { renderChip, chip, tab, text } = open('player_chip')
        renderChip('Not available here')

        expect(chip()?.textContent).toContain('From an email?')
        expect(chip()!.querySelector('a')).toBeNull()
        await tab()
        expect(text('Not available here')).not.toBeNull()
    })

    it('stays hidden for the rest of the page after its × is clicked, once storage fills after the app loaded', () => {
        const { renderChip, chip, click, captured } = open('player_chip')
        fillStorage()
        renderChip()
        expect(chip()).not.toBeNull()

        click(chip()!.querySelector<HTMLElement>('[aria-label="Hide for 90 days"]')!)
        expect(chip()).toBeNull()
        renderChip()
        expect(chip()).toBeNull()
        expect(captured('messaging cta dismissed')).toEqual([{ placement: 'replay.player_chip' }])
    })

    it('keeps a newer dismissal that another tab saved over its own', () => {
        jest.useFakeTimers({ now: new Date('2026-03-01T12:00:00Z') })
        const first = open('player_chip')
        first.renderChip()
        otherTab = openFreshPageLoad('player_chip', true)
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

    it('stays hidden and silent for 90 days after its × is clicked, for that viewer only', () => {
        jest.useFakeTimers({ now: new Date('2026-03-01T12:00:00Z') })
        const first = open('player_chip')
        first.renderChip()

        first.click(first.chip()!.querySelector<HTMLElement>('[aria-label="Hide for 90 days"]')!)
        expect(first.chip()).toBeNull()
        expect(first.captured('messaging cta dismissed')).toEqual([{ placement: 'replay.player_chip' }])

        jest.setSystemTime(Date.now() + 89 * DAY_MS)
        const later = open('player_chip')
        later.renderChip()
        expect(later.chip()).toBeNull()
        expect(later.captured('$feature_flag_called')).toEqual([])

        later.switchViewer('ANOTHER_USER_UUID')
        expect(later.chip()).not.toBeNull()

        jest.setSystemTime(Date.now() + DAY_MS)
        const afterNinetyDays = open('player_chip')
        afterNinetyDays.renderChip()
        expect(afterNinetyDays.chip()).not.toBeNull()
    })
})
