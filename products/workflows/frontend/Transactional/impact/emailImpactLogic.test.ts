import { MOCK_DEFAULT_TEAM, MOCK_TEAM_ID } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { dayjs } from 'lib/dayjs'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { teamLogic } from 'scenes/teamLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { TeamType } from '~/types'

import type { TransactionalEmailImpactApi } from 'products/messaging/frontend/generated/api.schemas'

import { emailImpactLogic } from './emailImpactLogic'

const ENVIRONMENT: TeamType = { ...MOCK_DEFAULT_TEAM, id: MOCK_TEAM_ID + 5, project_id: MOCK_TEAM_ID }

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

describe('emailImpactLogic', () => {
    let logic: ReturnType<typeof emailImpactLogic.build>
    let requestedFrom: string[]
    let requestedParams: URLSearchParams[]
    let answer: [number, unknown] | Promise<[number, unknown]>
    let onRequest: () => void

    beforeEach(() => {
        requestedFrom = []
        requestedParams = []
        answer = [200, IMPACT]
        onRequest = () => {}
        useMocks({
            get: {
                '/api/projects/:team_id/transactional_email_log/impact/': ({ params, request }) => {
                    requestedFrom.push(String(params.team_id))
                    requestedParams.push(new URL(request.url).searchParams)
                    onRequest()
                    return answer
                },
            },
        })
    })

    afterEach(() => logic.unmount())

    it('asks the environment the email belongs to, and says which sends it could follow', async () => {
        initKeaTests(true, ENVIRONMENT)
        logic = emailImpactLogic({ workflowId: 'workflow-1' })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        expect(requestedFrom).toEqual([String(ENVIRONMENT.id)])
        expect(logic.values.impact).toEqual(IMPACT)
        expect(logic.values.followedNote).toMatch(/^Counted over 1 of 2 clicked sends:/)
    })

    it('loads once the team arrives when the tab mounts first', async () => {
        initKeaTests(true, null as unknown as TeamType)
        logic = emailImpactLogic({ workflowId: 'workflow-1' })
        const requested = new Promise<void>((resolve) => (onRequest = resolve))
        logic.mount()
        await requested
        await expectLogic(logic).toFinishAllListeners()

        expect(requestedFrom).toEqual([String(teamLogic.values.currentTeamId)])
        expect(logic.values.impact).toEqual(IMPACT)
    })

    it.each([
        ['period', (): void => logic.actions.setDays(7), null, 7],
        ['event', (): void => logic.actions.setEvent('plan upgraded'), 'plan upgraded', 30],
    ])('shows the funnel as pending until a new %s answers', async (_, change, event, days) => {
        initKeaTests(true, ENVIRONMENT)
        logic = emailImpactLogic({ workflowId: 'workflow-1' })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        let answerNewSends: () => void = () => {}
        answer = new Promise((resolve) => {
            answerNewSends = () => resolve([200, { ...IMPACT, sent: 4 }])
        })

        const requested = new Promise<void>((resolve) => (onRequest = resolve))

        change()
        await requested

        expect(logic.values.funnelState).toBe('loading')
        const params = requestedParams[requestedParams.length - 1]
        expect(params.get('workflow_id')).toBe('workflow-1')
        expect(params.get('event')).toBe(event)
        expect(dayjs().diff(dayjs(params.get('date_from')), 'day')).toBe(days)
        answerNewSends()
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.funnelState).toBe('ready')
        expect(logic.values.impact?.sent).toBe(4)
    })

    it.each([
        [
            "a 403 with the server's reason",
            [403, { detail: 'You need access to querying events to count conversions.' }],
            'You need access to querying events to count conversions.',
        ],
        [
            'a server failure with the shorter-period hint',
            [500, { detail: 'Server error' }],
            "This email's impact couldn't load. Try again, or pick a shorter period.",
        ],
        [
            'a query limit with the wait hint',
            [429, { detail: 'Request was throttled.' }],
            'Too many queries are running for this project. Wait a minute, then try again.',
        ],
        [
            'a request failure without the shorter-period hint',
            [404, { detail: 'Not found.' }],
            "This email's impact couldn't load. Try again, and if it keeps failing, contact support.",
        ],
    ])('explains %s, and clears it once a retry answers', async (_, response, message) => {
        answer = response as [number, unknown]
        const toast = jest.spyOn(lemonToast, 'error')
        initKeaTests(true, ENVIRONMENT)
        logic = emailImpactLogic({ workflowId: 'workflow-1' })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.impactError).toBe(message)
        expect(logic.values.funnelState).toBe('error')
        expect(toast).not.toHaveBeenCalled()

        answer = [200, IMPACT]
        logic.actions.loadImpact()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.impactError).toBeNull()
        expect(logic.values.funnelState).toBe('ready')
    })
})
