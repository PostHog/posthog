import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { BindLogic, Provider } from 'kea'
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { OrganizationMembershipLevel } from 'lib/constants'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { mockEventDefinitions, mockGetEventDefinitionsFrom } from '~/test/mocks'
import { TeamType } from '~/types'

import type { TransactionalEmailImpactApi } from 'products/messaging/frontend/generated/api.schemas'

import { emailImpactLogic } from './emailImpactLogic'
import { EmailImpactTab } from './EmailImpactTab'
import { ImpactFunnelCard } from './ImpactFunnelCard'

const { ToastContainer } = jest.requireActual('react-toastify')

// react-virtualized renders no rows without real DOM measurements.
jest.mock('lib/components/AutoSizer', () => ({
    AutoSizer: ({ renderProp }: { renderProp: (size: { height: number; width: number }) => React.ReactNode }) =>
        renderProp({ height: 400, width: 400 }),
}))

const IMPACT: TransactionalEmailImpactApi = {
    sent: 10,
    delivered: 9,
    opened: 5,
    clicked: 2,
    not_clicked: 7,
    untracked: 0,
    window_days: 7,
    after_click: { sends: 1, converted: 0 },
    without_click: { sends: 7, converted: 1 },
}

const teamWithLinkTagging = (enabled: boolean | undefined): TeamType => ({
    ...MOCK_DEFAULT_TEAM,
    workflows_config: {
        capture_workflows_engagement_events: true,
        ...(enabled === undefined ? {} : { email_workflow_run_link_tag_enabled: enabled }),
    },
})

describe('ImpactFunnelCard', () => {
    let answer: [number, unknown]

    beforeEach(() => {
        localStorage.clear()
        useMocks({
            get: {
                '/api/projects/:team_id/transactional_email_log/impact/': ({ request }) => {
                    const [status, body] = answer
                    const named = new URL(request.url).searchParams.get('event')
                    return [status, named ? body : { ...(body as object), after_click: null, without_click: null }]
                },
            },
        })
        initKeaTests()
    })

    afterEach(cleanup)

    const renderCard = (sensitive = false): void => {
        render(
            <Provider>
                <BindLogic logic={emailImpactLogic} props={{ workflowId: 'workflow-1', alwaysSensitive: sensitive }}>
                    <ImpactFunnelCard />
                </BindLogic>
                <ToastContainer />
            </Provider>
        )
    }

    it.each([
        ['tagging is off', false, false, 'Link tracking is off', true],
        ['tagging is on', true, false, 'Not measured yet', false],
        ['the project never set tagging', undefined, false, 'Not measured yet', false],
        ['the email protects sensitive data', false, true, 'Not measured', false],
        ['the email protects sensitive data while tagging is on', true, true, 'Not measured', false],
    ])(
        'offers to turn on link tracking in place of the session and conversion steps only when it would help, when %s',
        async (_, enabled, sensitive, shown, prompted) => {
            const capture = jest.spyOn(posthog, 'capture')
            initKeaTests(true, teamWithLinkTagging(enabled))
            answer = [200, IMPACT]
            renderCard(sensitive)

            expect(await screen.findByText(shown)).toBeInTheDocument()
            expect(!!screen.queryByText('Turn on for project')).toBe(prompted)
            expect(!!screen.queryByText('Started a session')).toBe(!prompted)
            expect(!!screen.queryByText('Converted')).toBe(!prompted)
            expect(capture).toHaveBeenCalledWith(
                'transactional email impact loaded',
                expect.objectContaining({ shows_link_tracking_prompt: prompted })
            )
        }
    )

    it.each([
        ['turns it on for the project and shows both steps again', [200, null], 'Not measured yet', true],
        [
            'says why when saving fails, and offers it again',
            [500, { detail: 'Saving failed' }],
            /Saving failed$/,
            false,
        ],
    ] as const)('turns on link tracking from the funnel: %s', async (_, saveAnswer, outcome, turnedOn) => {
        const capture = jest.spyOn(posthog, 'capture')
        const team = teamWithLinkTagging(false)
        const patches: Partial<TeamType>[] = []
        let answerSave: () => void = () => {}
        const saved = new Promise<void>((resolve) => (answerSave = resolve))
        useMocks({
            patch: {
                '/api/projects/:id': async ({ request }) => {
                    patches.push((await request.json()) as Partial<TeamType>)
                    await saved
                    const [status, body] = saveAnswer
                    return [
                        status,
                        body ?? {
                            ...team,
                            workflows_config: { ...team.workflows_config, ...patches[0].workflows_config },
                        },
                    ]
                },
            },
        })
        initKeaTests(true, team)
        answer = [200, IMPACT]
        renderCard()

        fireEvent.click(await screen.findByText('Turn on for project'))

        await waitFor(() =>
            expect(patches).toEqual([{ workflows_config: { email_workflow_run_link_tag_enabled: true } }])
        )
        expect(screen.getByText('Turn on for project').closest('button')).toHaveAttribute('aria-disabled', 'true')
        answerSave()

        expect((await screen.findAllByText(outcome))[0]).toBeInTheDocument()
        expect(!!screen.queryByText('Converted')).toBe(turnedOn)
        expect(
            screen.queryByText('Turn on for project')?.closest('button')?.getAttribute('aria-disabled') ?? null
        ).toBe(turnedOn ? null : 'false')
        expect(
            capture.mock.calls.filter(([name]) => name === 'transactional email impact link tracking turned on')
        ).toHaveLength(turnedOn ? 1 : 0)
    })

    it("keeps link tracking off for someone who can't change project settings", async () => {
        const patches: unknown[] = []
        useMocks({ patch: { '/api/projects/:id': async ({ request }) => [200, patches.push(await request.json())] } })
        initKeaTests(true, {
            ...teamWithLinkTagging(false),
            effective_membership_level: OrganizationMembershipLevel.Member,
        })
        answer = [200, IMPACT]
        renderCard()

        const button = (await screen.findByText('Turn on for project')).closest('button')
        expect(button).toHaveAttribute('aria-disabled', 'true')
        fireEvent.click(button as HTMLButtonElement)

        const logic = emailImpactLogic({ workflowId: 'workflow-1' })
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.linkTrackingTurningOn).toBe(false)
        expect(screen.getByText('Link tracking is off')).toBeInTheDocument()
        expect(patches).toEqual([])
    })

    it('picks the conversion event from the empty conversion step', async () => {
        const capture = jest.spyOn(posthog, 'capture')
        useMocks({
            get: {
                '/api/projects/:team/event_definitions': mockGetEventDefinitionsFrom([
                    { ...mockEventDefinitions[0], id: 'plan-upgraded', name: 'plan upgraded' },
                ]),
            },
        })
        initKeaTests(true, teamWithLinkTagging(true))
        answer = [200, IMPACT]
        renderCard()

        fireEvent.click(await screen.findByTestId('email-impact-funnel-event'))
        fireEvent.click(await screen.findByText('plan upgraded'))

        expect(await screen.findByText('From send to "plan upgraded"')).toBeInTheDocument()
        expect(emailImpactLogic({ workflowId: 'workflow-1' }).values.event).toBe('plan upgraded')
        expect(capture).toHaveBeenCalledWith('transactional email impact event picked', {
            source: 'funnel',
            cleared: false,
        })
    })

    it("shows a template's new sensitivity on a mounted Impact tab", async () => {
        initKeaTests(true, teamWithLinkTagging(false))
        answer = [200, IMPACT]
        const tab = (alwaysSensitive: boolean): JSX.Element => (
            <Provider>
                <EmailImpactTab workflowId="workflow-1" alwaysSensitive={alwaysSensitive} />
            </Provider>
        )
        const { rerender } = render(tab(false))
        await screen.findByText('Link tracking is off')

        rerender(tab(true))

        expect(await screen.findByText('Not measured')).toBeInTheDocument()
    })

    it.each([
        { untracked: 0, note: null },
        { untracked: 3, note: /^3 sends in this period went out with tracking off/ },
    ])(
        'says no sends were recorded for an empty period with $untracked untracked sends',
        async ({ untracked, note }) => {
            answer = [200, { ...IMPACT, sent: 0, delivered: 0, opened: 0, clicked: 0, not_clicked: 0, untracked }]
            renderCard()

            expect(await screen.findByText('No sends of this email were recorded in this period.')).toBeInTheDocument()
            if (note) {
                expect(screen.getByText(note)).toBeInTheDocument()
            } else {
                expect(screen.queryByText(/tracking off/)).not.toBeInTheDocument()
            }
        }
    )

    it('draws opens and clicks that arrived before their sends', async () => {
        answer = [
            200,
            {
                ...IMPACT,
                sent: 0,
                delivered: 0,
                opened: 4,
                clicked: 1,
                not_clicked: 0,
                after_click: { sends: 1, converted: 0 },
                without_click: { sends: 0, converted: 0 },
            },
        ]
        renderCard()

        expect((await screen.findByTestId('email-impact-bar-opened')).style.height).toBe('100%')
        expect(screen.getByTestId('email-impact-bar-clicked').style.height).toBe('25%')
        expect(screen.queryByTestId('email-impact-bar-sent')).not.toBeInTheDocument()
        expect(screen.queryByTestId('email-impact-bar-delivered')).not.toBeInTheDocument()
    })

    it.each([
        [
            'every click went untracked',
            { opened: 0, clicked: 0, untracked: 10 },
            'No clicks were recorded, because every send in this period went out with tracking off.',
            '',
        ],
        ['no tracked send was clicked', { clicked: 0 }, 'No clicks were recorded in this period.', ''],
        [
            'every send went untracked but an open was recorded',
            { opened: 1, clicked: 0, untracked: 10 },
            'No clicks were recorded in this period.',
            '',
        ],
        [
            'no clicked send could be followed',
            { clicked: 2 },
            'PostHog followed none of the clicked sends.',
            ' Counted over 0 of 2 clicked sends: PostHog follows the sends that name a person, and only the most recent ones on a busy email.',
        ],
    ])(
        'says why no click is compared, and still compares delivered sends, when %s',
        async (_, counts, reason, note) => {
            answer = [
                200,
                {
                    ...IMPACT,
                    not_clicked: 9,
                    ...counts,
                    after_click: { sends: 0, converted: 0 },
                    without_click: { sends: 9, converted: 3 },
                },
            ]
            renderCard()
            emailImpactLogic({ workflowId: 'workflow-1' }).actions.setEvent('plan upgraded')

            const lift = (await screen.findByText(reason)).closest('p')
            expect(lift).toHaveTextContent(
                `${reason} 33.3% of delivered sends with no recorded click were followed by plan upgraded within 7 days of the send.${note}`
            )
        }
    )

    it('says why no conversion is counted when no send in either group could be followed', async () => {
        answer = [
            200,
            { ...IMPACT, after_click: { sends: 0, converted: 0 }, without_click: { sends: 0, converted: 0 } },
        ]
        renderCard()
        emailImpactLogic({ workflowId: 'workflow-1' }).actions.setEvent('plan upgraded')

        const reason = await screen.findByText(/^PostHog followed none of the sends in this period/)
        expect(reason.closest('p')).toHaveTextContent(
            'PostHog followed none of the sends in this period to see who did plan upgraded. Counted over 0 of 2 clicked sends and 0 of 7 delivered sends with no recorded click: PostHog follows the sends that name a person, and only the most recent ones on a busy email.'
        )
    })

    it('shows a failed load once, in the card, and loads the funnel on Try again', async () => {
        answer = [500, { detail: 'Server error' }]
        renderCard()

        expect(
            await screen.findByText("This email's impact couldn't load. Try again, or pick a shorter period.")
        ).toBeInTheDocument()
        expect(screen.queryByText(/Load impact failed/)).not.toBeInTheDocument()

        answer = [200, IMPACT]
        fireEvent.click(screen.getAllByText('Try again')[0])

        expect(await screen.findByText('Delivered')).toBeInTheDocument()
        expect(screen.queryByText(/couldn't load/)).not.toBeInTheDocument()
    })
})
