import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { BindLogic, Provider } from 'kea'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { TransactionalEmailImpactApi } from 'products/messaging/frontend/generated/api.schemas'

import { emailImpactLogic } from './emailImpactLogic'
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

    const renderCard = (): void => {
        render(
            <Provider>
                <BindLogic logic={emailImpactLogic} props={{ workflowId: 'workflow-1' }}>
                    <ImpactFunnelCard />
                </BindLogic>
                <ToastContainer />
            </Provider>
        )
    }

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
