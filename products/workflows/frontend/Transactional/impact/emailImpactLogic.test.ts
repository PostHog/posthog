import { MOCK_DEFAULT_TEAM, MOCK_TEAM_ID } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

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
    let answer: [number, unknown] | Promise<[number, unknown]>

    beforeEach(() => {
        requestedFrom = []
        answer = [200, IMPACT]
        useMocks({
            get: {
                '/api/projects/:team_id/transactional_email_log/impact/': ({ params }) => {
                    requestedFrom.push(String(params.team_id))
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
        logic.mount()
        await expectLogic(teamLogic).toDispatchActions(['loadCurrentTeamSuccess'])
        await expectLogic(logic).toFinishAllListeners()

        expect(requestedFrom).toEqual([String(teamLogic.values.currentTeamId)])
        expect(logic.values.impact).toEqual(IMPACT)
    })

    it.each([
        ['period', (): void => logic.actions.setDays(7)],
        ['event', (): void => logic.actions.setEvent('plan upgraded')],
    ])('shows the funnel as pending until a new %s answers', async (_, change) => {
        initKeaTests(true, ENVIRONMENT)
        logic = emailImpactLogic({ workflowId: 'workflow-1' })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        let answerNewSends: () => void = () => {}
        answer = new Promise((resolve) => {
            answerNewSends = () => resolve([200, { ...IMPACT, sent: 4 }])
        })

        change()
        await expectLogic(logic).toDispatchActions(['loadImpact']).delay(150)

        expect(requestedFrom).toHaveLength(2)
        expect(logic.values.funnelState).toBe('loading')
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
            'any other failure with the retry hint',
            [500, { detail: 'Server error' }],
            "This email's impact couldn't load. Try again, or pick a shorter period.",
        ],
    ])('explains %s', async (_, response, message) => {
        answer = response as [number, unknown]
        initKeaTests(true, ENVIRONMENT)
        logic = emailImpactLogic({ workflowId: 'workflow-1' })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.impactError).toBe(message)
    })
})
