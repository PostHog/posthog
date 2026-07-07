import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { BriefConfigApi, ProductBriefApi } from './generated/api.schemas'
import {
    BRIEF_ALREADY_GENERATING_MESSAGE,
    CITATION_TYPES,
    MAX_CONSECUTIVE_POLL_FAILURES,
    pulseLogic,
} from './pulseLogic'

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

    it('stops polling with an error toast after consecutive all-failed poll rounds', async () => {
        const errorSpy = jest.spyOn(lemonToast, 'error')
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
                .toNotHaveDispatchedActions(['stopPolling'])
        }

        // The failure ceiling stops the interval and surfaces the stuck state.
        await expectLogic(logic, () => {
            logic.actions.pollGeneratingBriefs()
        })
            .toFinishAllListeners()
            .toDispatchActions(['stopPolling'])
        expect(errorSpy).toHaveBeenCalled()
        expect(logic.values.briefs[0].status).toEqual('generating')
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

    it.each([
        [
            'citation without separator',
            { kind: 'k', title: 't', markdown: 'm', citations: ['noseparator'], confidence: 0.5 },
            { kind: 'k', title: 't', markdown: 'm', citations: [{ type: '', ref: 'noseparator' }], confidence: 0.5 },
        ],
        [
            'citation with leading separator',
            { kind: 'k', title: 't', markdown: 'm', citations: [':leading'], confidence: 0.5 },
            { kind: 'k', title: 't', markdown: 'm', citations: [{ type: '', ref: ':leading' }], confidence: 0.5 },
        ],
        [
            'section missing kind, title, and markdown',
            {},
            { kind: '', title: '', markdown: '', citations: [], confidence: 0 },
        ],
        [
            'non-array citations and non-number confidence',
            { kind: 'k', title: 't', markdown: 'm', citations: 'nope', confidence: 'high' },
            { kind: 'k', title: 't', markdown: 'm', citations: [], confidence: 0 },
        ],
    ])('parses malformed brief sections: %s', (_name, section, expected) => {
        logic.actions.loadBriefDetailSuccess({ ...readyBrief, sections: [section] } as unknown as ProductBriefApi)
        expect(logic.values.briefDetailSections[0]).toEqual(expected)
    })

    it.each<[string, string, string | undefined]>([
        ['insight', 'abc123', '/insights/abc123'],
        ['dashboard', '5', '/dashboard/5'],
        ['flag', '123', '/feature_flags/123'],
        ['experiment', '45', '/experiments/45'],
        ['annotation', '77', '/data-management/annotations/77'],
        // A hallucinated non-numeric ref renders unlinked instead of a dead /NaN link.
        ['flag', 'not-a-number', undefined],
        // Empty-string and "0" are finite numbers but not real ids — must not link to resource 0.
        ['flag', '', undefined],
        ['experiment', '0', undefined],
    ])('maps %s:%s citations to a scene URL', (type, ref, expected) => {
        expect(CITATION_TYPES[type].url(ref)).toEqual(expected)
    })

    it('has no citation table entry for unknown types, which render unlinked', () => {
        expect(CITATION_TYPES['signal_report']).toBeUndefined()
    })
})
