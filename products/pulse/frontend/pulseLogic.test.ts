import { expectLogic } from 'kea-test-utils'

import { lemonToast } from 'lib/lemon-ui/LemonToast'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { pulseLogic } from './pulseLogic'

const generatingBrief = {
    id: 'brief-1',
    config: null,
    status: 'generating',
    trigger: 'on_demand',
    period_days: 7,
    sections: [],
    sources_used: [],
    error: null,
    created_at: '2026-07-02T10:00:00Z',
    created_by: null,
    updated_at: null,
}

const readyBrief = {
    ...generatingBrief,
    status: 'ready',
    sections: [
        {
            kind: 'what_happened',
            title: 'Signups dipped',
            markdown: 'Signup conversion dropped 12%.',
            citations: ['insight:abc123'],
            confidence: 0.9,
        },
    ],
    sources_used: ['anchored_insights'],
}

describe('pulseLogic', () => {
    let logic: ReturnType<typeof pulseLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team_id/pulse/brief_configs/': { count: 0, results: [] },
                '/api/projects/:team_id/pulse/briefs/': { count: 0, results: [] },
                '/api/projects/:team_id/pulse/briefs/:id/': readyBrief,
            },
            post: {
                '/api/projects/:team_id/pulse/briefs/generate/': () => [201, generatingBrief],
            },
        })
        initKeaTests()
        logic = pulseLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    it('generates a brief, polls it, and stops polling on terminal status', async () => {
        await expectLogic(logic, () => {
            logic.actions.generateBrief({ configId: null })
        })
            .toDispatchActions(['generateBriefSuccess', 'startPolling'])
            .toMatchValues({
                selectedBriefId: 'brief-1',
                isGenerating: true,
            })

        // A poll tick that finds the brief in a terminal state must merge it in and stop the interval.
        await expectLogic(logic, () => {
            logic.actions.pollGeneratingBriefs()
        })
            .toDispatchActions(['briefsRefreshed', 'stopPolling'])
            .toMatchValues({ isGenerating: false })
        expect(logic.values.briefs[0].status).toEqual('ready')
        expect(logic.values.briefDetail?.sections).toHaveLength(1)

        // With nothing generating, another tick must not fetch or refresh anything.
        await expectLogic(logic, () => {
            logic.actions.pollGeneratingBriefs()
        }).toNotHaveDispatchedActions(['briefsRefreshed'])
    })

    it('surfaces the consent banner on an AI data processing 400 without starting polling', async () => {
        useMocks({
            post: {
                '/api/projects/:team_id/pulse/briefs/generate/': () => [
                    400,
                    { detail: 'AI data processing must be approved for this organization to generate briefs.' },
                ],
            },
        })

        await expectLogic(logic, () => {
            logic.actions.generateBrief({ configId: null })
        })
            .toFinishAllListeners()
            .toMatchValues({
                aiConsentRequired: true,
                generatedBrief: null,
                briefs: [],
            })
        await expectLogic(logic).toNotHaveDispatchedActions(['startPolling'])
    })

    it('toasts on a 409 generation conflict without touching the brief list', async () => {
        silenceKeaLoadersErrors()
        const infoSpy = jest.spyOn(lemonToast, 'info')
        useMocks({
            post: {
                '/api/projects/:team_id/pulse/briefs/generate/': () => [
                    409,
                    { detail: 'Brief generation already in progress' },
                ],
            },
        })

        await expectLogic(logic, () => {
            logic.actions.generateBrief({ configId: null })
        })
            .toDispatchActions(['generateBriefFailure'])
            .toMatchValues({
                aiConsentRequired: false,
                briefs: [],
            })
        expect(infoSpy).toHaveBeenCalledWith('A brief is already being generated')
        await expectLogic(logic).toNotHaveDispatchedActions(['startPolling'])
        resumeKeaLoadersErrors()
    })
})
