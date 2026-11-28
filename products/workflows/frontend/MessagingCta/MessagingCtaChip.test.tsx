import { MOCK_DEFAULT_USER } from 'lib/api.mock'

import { FEATURE_FLAGS } from 'lib/constants'

import { AccessControlLevel, AccessControlResourceType, AppContext } from '~/types'

const CHIP = 'messaging-cta-chip-replay.player_chip'
const DAY_MS = 24 * 60 * 60 * 1000

interface Page {
    renderChip: (disabledReason?: string) => void
    chip: () => HTMLElement | null
    click: (element: HTMLElement, init?: MouseEventInit) => void
    middleClick: (element: HTMLElement) => void
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
            middleClick: (element) => rtl.fireEvent(element, new MouseEvent('auxclick', { bubbles: true, button: 1 })),
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
        jest.useRealTimers()
    })

    test.each([
        { name: 'the control arm', arm: 'control', access: AccessControlLevel.Editor, exposed: true },
        { name: 'the holdout', arm: 'holdout-1', access: AccessControlLevel.Editor, exposed: true },
        { name: 'an unset flag', arm: undefined, access: AccessControlLevel.Editor, exposed: false },
        { name: 'a false flag', arm: false, access: AccessControlLevel.Editor, exposed: false },
        { name: 'a viewer without edit access', arm: 'player_chip', access: AccessControlLevel.Viewer, exposed: false },
        {
            name: 'a team that cannot send email from code',
            arm: 'player_chip',
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
        const { renderChip, chip, click, middleClick, captured } = open('player_chip')
        renderChip()
        renderChip()

        expect(chip()?.textContent).toContain('From an email?')
        expect(captured('$feature_flag_called')).toEqual([
            { $feature_flag: FEATURE_FLAGS.XPM_REPLAY_PLACEMENT, $feature_flag_response: 'player_chip' },
        ])

        const link = chip()!.querySelector('a')!
        expect(link.getAttribute('href')).toMatch(/\/transactional\/new$/)
        click(link)
        click(link, { ctrlKey: true })
        click(link, { metaKey: true })
        middleClick(link)
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

    it('shows its copy without a link when the host gives a reason it is disabled', () => {
        const { renderChip, chip } = open('player_chip')
        renderChip('Not available here')

        expect(chip()?.textContent).toContain('From an email?')
        expect(chip()!.querySelector('a')).toBeNull()
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
