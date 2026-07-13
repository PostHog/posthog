import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { FEATURE_FLAGS } from 'lib/constants'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { BriefConfigApi, ProductBriefListApi } from './generated/api.schemas'
import { BRIEF_ALREADY_GENERATING_MESSAGE, MAX_CONSECUTIVE_POLL_FAILURES, pulseLogic } from './pulseLogic'

const generatingBrief = {
    id: 'brief-1',
    config: null,
    status: 'generating',
    trigger: 'on_demand',
    period: { period_type: 'last_n_days', days: 7 },
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
            citations: [{ type: 'insight', ref: 'abc123', label: 'Signups', url: '/project/1/insights/abc123' }],
            confidence: 0.9,
        },
    ],
    sources_used: ['anchored_insights'],
}

const existingConfig: BriefConfigApi = {
    id: 'cfg-1',
    name: 'Flags team',
    focus_prompt: 'flags',
    anchors: { dashboards: [1], insights: ['abc123'] },
    enabled: true,
    created_at: '2026-07-01T00:00:00Z',
    created_by: null,
    updated_at: null,
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
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.PULSE], { [FEATURE_FLAGS.PULSE]: true })
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
                isGeneratingForSelectedConfig: true,
            })

        // A poll tick that finds the brief in a terminal state merges it in.
        await expectLogic(logic, () => {
            logic.actions.pollGeneratingBriefs()
        })
            .toDispatchActions(['briefsRefreshed'])
            .toMatchValues({ isGeneratingForSelectedConfig: false })
        expect(logic.values.briefs[0].status).toEqual('ready')
        expect(logic.values.briefDetail?.sections).toHaveLength(1)

        // The next tick finds nothing generating: it stops the interval without fetching.
        await expectLogic(logic, () => {
            logic.actions.pollGeneratingBriefs()
        })
            .toDispatchActions(['stopPolling'])
            .toNotHaveDispatchedActions(['briefsRefreshed'])
    })

    it('marks a brief failed after consecutive poll failures, then stops polling', async () => {
        const captureSpy = jest.spyOn(posthog, 'capture')
        useMocks({
            get: { '/api/projects/:team_id/pulse/briefs/:id/': () => [500, {}] },
        })

        await expectLogic(logic, () => {
            logic.actions.generateBrief({ configId: null })
        }).toDispatchActions(['startPolling'])

        for (let round = 1; round < MAX_CONSECUTIVE_POLL_FAILURES; round++) {
            await expectLogic(logic, () => {
                logic.actions.pollGeneratingBriefs()
            })
                .toFinishAllListeners()
                .toNotHaveDispatchedActions(['markBriefFailed'])
        }

        // The failure ceiling marks the stuck brief failed rather than spinning on "generating" forever.
        await expectLogic(logic, () => {
            logic.actions.pollGeneratingBriefs()
        })
            .toFinishAllListeners()
            .toDispatchActions(['markBriefFailed'])
        expect(logic.values.briefs[0].status).toEqual('failed')
        expect(captureSpy).toHaveBeenCalledWith('pulse brief poll gave up', { brief_id: 'brief-1' })

        // With nothing left generating, the next tick ends the interval.
        await expectLogic(logic, () => {
            logic.actions.pollGeneratingBriefs()
        }).toDispatchActions(['stopPolling'])
    })

    it('fails only the unreachable brief while a sibling keeps updating', async () => {
        const briefOk: ProductBriefListApi = { ...generatingBrief, id: 'brief-ok' } as unknown as ProductBriefListApi
        const briefBad: ProductBriefListApi = { ...generatingBrief, id: 'brief-bad' } as unknown as ProductBriefListApi
        useMocks({
            get: {
                '/api/projects/:team_id/pulse/briefs/:id/': (info) =>
                    info.request.url.includes('brief-bad') ? [500, {}] : [200, { ...briefOk, status: 'ready' }],
            },
        })
        await expectLogic(logic).toFinishAllListeners() // let the mount-time loads settle before seeding
        logic.actions.loadBriefsSuccess([briefOk, briefBad])
        logic.actions.startPolling()

        // A shared failure counter would reset every time the sibling succeeds, so the bad brief
        // would never trip the ceiling — the per-brief counter must still fail it.
        for (let round = 1; round <= MAX_CONSECUTIVE_POLL_FAILURES; round++) {
            await expectLogic(logic, () => {
                logic.actions.pollGeneratingBriefs()
            }).toFinishAllListeners()
        }

        const byId = Object.fromEntries(logic.values.briefs.map((brief) => [brief.id, brief]))
        expect(byId['brief-ok'].status).toEqual('ready')
        expect(byId['brief-bad'].status).toEqual('failed')
    })

    it('surfaces the consent banner on an AI data processing 400 without starting polling', async () => {
        useMocks({
            post: {
                '/api/projects/:team_id/pulse/briefs/generate/': () => [
                    400,
                    {
                        type: 'validation_error',
                        code: 'ai_consent_required',
                        detail: 'AI data processing must be approved for this organization to generate briefs.',
                        attr: null,
                    },
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
        expect(infoSpy).toHaveBeenCalledWith(BRIEF_ALREADY_GENERATING_MESSAGE)
        await expectLogic(logic).toNotHaveDispatchedActions(['startPolling'])
        resumeKeaLoadersErrors()
    })

    it.each<[string, BriefConfigApi | null, 'post' | 'patch', Record<string, unknown>]>([
        ['create', null, 'post', { dashboards: [2] }],
        // Insight anchors set through the API must survive a save from this dashboards-only form.
        ['edit', existingConfig, 'patch', { dashboards: [2], insights: ['abc123'] }],
    ])(
        'saving a config in %s mode hits the %s endpoint with the form payload',
        async (_mode, editing, endpoint, expectedAnchors) => {
            const captured: Record<'post' | 'patch', Record<string, any> | null> = { post: null, patch: null }
            useMocks({
                post: {
                    '/api/projects/:team_id/pulse/brief_configs/': async (info) => {
                        captured.post = (await info.request.json()) as Record<string, any>
                        return [201, { ...existingConfig, ...captured.post, id: 'cfg-new' }]
                    },
                },
                patch: {
                    '/api/projects/:team_id/pulse/brief_configs/:id/': async (info) => {
                        captured.patch = (await info.request.json()) as Record<string, any>
                        return [200, { ...existingConfig, ...captured.patch }]
                    },
                },
            })

            logic.actions.openConfigModal(editing)
            logic.actions.setConfigFormValues({ name: 'Updated name', dashboards: [2] })
            await expectLogic(logic, () => {
                logic.actions.submitConfigForm()
            }).toDispatchActions(['configSaved'])

            expect(captured[endpoint === 'post' ? 'patch' : 'post']).toBeNull()
            expect(captured[endpoint]!.name).toEqual('Updated name')
            expect(captured[endpoint]!.anchors).toEqual(expectedAnchors)
            // A newly created config is auto-selected; editing an existing one leaves selection untouched.
            expect(logic.values.selectedConfigId).toEqual(endpoint === 'post' ? 'cfg-new' : null)
        }
    )

    it('keeps the config and clears the deleting state when delete fails', async () => {
        const errorSpy = jest.spyOn(lemonToast, 'error')
        useMocks({
            delete: { '/api/projects/:team_id/pulse/brief_configs/:id/': () => [500, {}] },
        })
        await expectLogic(logic).toFinishAllListeners() // let the mount-time loads settle before seeding
        logic.actions.loadBriefConfigsSuccess([existingConfig])

        await expectLogic(logic, () => {
            logic.actions.deleteConfig('cfg-1')
        })
            .toFinishAllListeners()
            .toMatchValues({ configIdBeingDeleted: null })
        expect(logic.values.briefConfigs).toHaveLength(1)
        expect(errorSpy).toHaveBeenCalled()
    })

    it('resets selection when the active config is deleted', async () => {
        useMocks({
            delete: { '/api/projects/:team_id/pulse/brief_configs/:id/': () => [204] },
        })
        await expectLogic(logic).toFinishAllListeners() // let the mount-time loads settle before seeding
        logic.actions.loadBriefConfigsSuccess([existingConfig])
        logic.actions.selectConfig('cfg-1')

        await expectLogic(logic, () => {
            logic.actions.deleteConfig('cfg-1')
        })
            .toDispatchActions(['configDeleted'])
            .toMatchValues({ selectedConfigId: null, briefConfigs: [] })
    })
})
