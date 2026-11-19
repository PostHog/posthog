import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { BindLogic, Provider } from 'kea'
import { router } from 'kea-router'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { TeamType } from '~/types'

import type { TransactionalEmailImpactApi } from 'products/messaging/frontend/generated/api.schemas'
import { WorkflowsRunLinkTagSettings } from 'products/workflows/frontend/scenes/settings/WorkflowsRunLinkTagSettings'

import { emailImpactLogic } from './emailImpactLogic'
import { EmailImpactTab } from './EmailImpactTab'
import { ImpactFunnelCard } from './ImpactFunnelCard'

const { ToastContainer } = jest.requireActual('react-toastify')

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

const teamWithLinkTagging = (enabled: boolean): TeamType => ({
    ...MOCK_DEFAULT_TEAM,
    workflows_config: { capture_workflows_engagement_events: true, email_workflow_run_link_tag_enabled: enabled },
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
        ['tagging is off', false, false, 'Needs link tagging', true],
        ['tagging is on', true, false, 'Not measured yet', false],
        ['the email protects sensitive data', false, true, 'Not measured', false],
    ])(
        "links the session step to the project's link tagging setting only when it would help, when %s",
        async (_, enabled, sensitive, label, linked) => {
            initKeaTests(true, teamWithLinkTagging(enabled))
            answer = [200, IMPACT]
            renderCard(sensitive)

            const step = await screen.findByText(label)
            expect(step.closest('a')?.getAttribute('href') ?? null).toEqual(
                linked ? expect.stringMatching(/\/settings\/environment-workflows#workflows-email-run-link-tag$/) : null
            )
            expect(step.closest('a')?.getAttribute('target') ?? null).toBe(null)
        }
    )

    it('shows the setting saved on the settings page once the user is back on the Impact tab', async () => {
        initKeaTests(true, teamWithLinkTagging(false))
        const saveTeam = async ({ request }: { request: Request }): Promise<[number, TeamType]> => {
            const { workflows_config } = (await request.json()) as Pick<TeamType, 'workflows_config'>
            return [200, { ...teamWithLinkTagging(false), workflows_config }]
        }
        useMocks({ patch: { '/api/projects/:id/': saveTeam, '/api/environments/:id/': saveTeam } })
        answer = [200, IMPACT]
        renderCard()
        fireEvent.click(await screen.findByText('Needs link tagging'))
        expect(router.values.location.pathname).toMatch(/\/settings\/environment-workflows$/)
        expect(router.values.hashParams).toHaveProperty('workflows-email-run-link-tag')
        cleanup()

        render(<WorkflowsRunLinkTagSettings />)
        fireEvent.click(screen.getByLabelText('Connect tracked email clicks to sessions'))
        await waitFor(() =>
            expect(screen.getByLabelText('Connect tracked email clicks to sessions')).toHaveAttribute(
                'aria-checked',
                'true'
            )
        )
        cleanup()

        renderCard()
        expect(await screen.findByText('Not measured yet')).toBeInTheDocument()
        expect(screen.queryByText('Needs link tagging')).not.toBeInTheDocument()
    })

    it.each([
        ['a Cmd-click', (link: HTMLElement) => fireEvent.click(link, { metaKey: true })],
        [
            'a middle-click',
            (link: HTMLElement) => fireEvent(link, new MouseEvent('auxclick', { bubbles: true, button: 1 })),
        ],
    ])(
        'shows the setting saved in another tab after %s on the link, once this tab has focus again',
        async (_, open) => {
            initKeaTests(true, teamWithLinkTagging(false))
            const savedTeam = teamWithLinkTagging(true)
            useMocks({ get: { '/api/environments/:id/': savedTeam, '/api/projects/:id/': savedTeam } })
            answer = [200, IMPACT]
            renderCard()

            open(await screen.findByText('Needs link tagging'))
            fireEvent(window, new Event('focus'))

            expect(await screen.findByText('Not measured yet')).toBeInTheDocument()
        }
    )

    it("shows a template's new sensitivity on a mounted Impact tab", async () => {
        initKeaTests(true, teamWithLinkTagging(false))
        answer = [200, IMPACT]
        const tab = (alwaysSensitive: boolean): JSX.Element => (
            <Provider>
                <EmailImpactTab workflowId="workflow-1" alwaysSensitive={alwaysSensitive} />
            </Provider>
        )
        const { rerender } = render(tab(false))
        await screen.findByText('Needs link tagging')

        rerender(tab(true))

        expect(await screen.findByText('Not measured')).toBeInTheDocument()
    })

    it('keeps the untracked note under an empty period', async () => {
        answer = [200, { ...IMPACT, sent: 0, delivered: 0, opened: 0, clicked: 0, not_clicked: 0, untracked: 3 }]
        renderCard()

        expect(await screen.findByText('No sends of this email were recorded in this period.')).toBeInTheDocument()
        expect(screen.getByText(/^3 sends in this period went out with tracking off/)).toBeInTheDocument()
    })

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
