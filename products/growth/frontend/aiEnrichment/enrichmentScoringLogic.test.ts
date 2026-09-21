import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { ScoringConfigApi, ScoringPreviewResponseApi } from '../generated/api.schemas'
import { enrichmentScoringLogic } from './enrichmentScoringLogic'

const ACTIVE_CONFIG: ScoringConfigApi = {
    id: 'active-config',
    version: 'v1',
    source: "return {'status': 'scored', 'score': 42, 'components': {'ai': 0}};",
    is_active: true,
    created_at: '2026-09-21T00:00:00Z',
    created_by_email: 'staff@example.com',
}
const DRAFT_CONFIG: ScoringConfigApi = {
    ...ACTIVE_CONFIG,
    id: 'draft-config',
    version: 'v2',
    source: "return {'status': 'scored', 'score': 57, 'components': {'ai': 15}};",
    is_active: false,
}
const PREVIEW: ScoringPreviewResponseApi = {
    results: [
        {
            company: 'Example company',
            domain: 'example.com',
            inputs: { ai_pilled: true },
            active: { status: 'scored', dq_reason: null, low_confidence: false, score: 42, components: { ai: 0 } },
            preview: { status: 'scored', dq_reason: null, low_confidence: false, score: 57, components: { ai: 15 } },
            error: null,
        },
    ],
    summary: { evaluated: 1, changed: 1, errors: 0 },
}

describe('enrichmentScoringLogic', () => {
    let logic: ReturnType<typeof enrichmentScoringLogic.build>

    beforeEach(async () => {
        useMocks({
            get: {
                '/api/growth_enrichment_scoring/configs/': {
                    results: [ACTIVE_CONFIG],
                    default_source: ACTIVE_CONFIG.source,
                },
            },
        })
        initKeaTests()
        logic = enrichmentScoringLogic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadConfigsSuccess'])
    })

    afterEach(() => logic.unmount())

    it('saves a new version without activating it, then activates only the saved version', async () => {
        const saves: unknown[] = []
        const activations: unknown[] = []
        let configs = [ACTIVE_CONFIG]
        useMocks({
            get: {
                '/api/growth_enrichment_scoring/configs/': () => ({
                    results: configs,
                    default_source: ACTIVE_CONFIG.source,
                }),
            },
            post: {
                '/api/growth_enrichment_scoring/save/': async ({ request }) => {
                    saves.push(await request.json())
                    configs = [ACTIVE_CONFIG, DRAFT_CONFIG]
                    return [201, DRAFT_CONFIG]
                },
                '/api/growth_enrichment_scoring/activate/': async ({ request }) => {
                    activations.push(await request.json())
                    configs = [
                        { ...ACTIVE_CONFIG, is_active: false },
                        { ...DRAFT_CONFIG, is_active: true },
                    ]
                    return configs[1]
                },
            },
        })
        logic.actions.setSource(DRAFT_CONFIG.source)
        await expectLogic(logic, () => logic.actions.saveFormula('v2')).toFinishAllListeners()

        expect(saves).toEqual([{ source: DRAFT_CONFIG.source, version: 'v2', base_config_id: ACTIVE_CONFIG.id }])
        expect(activations).toEqual([])
        expect(logic.values.activeConfig?.id).toBe(ACTIVE_CONFIG.id)
        expect(logic.values.selectedConfig?.id).toBe(DRAFT_CONFIG.id)
        expect(logic.values.isDirty).toBe(false)

        await expectLogic(logic, () => logic.actions.activateFormula(DRAFT_CONFIG.id)).toFinishAllListeners()
        expect(activations).toEqual([{ config_id: DRAFT_CONFIG.id }])
        expect(logic.values.activeConfig?.id).toBe(DRAFT_CONFIG.id)
        expect(logic.values.selectedConfig?.is_active).toBe(true)
    })

    it('keeps unsaved formula edits when the version list refreshes', async () => {
        logic.actions.setSource(DRAFT_CONFIG.source)
        await expectLogic(logic, () => logic.actions.loadConfigs()).toFinishAllListeners()
        expect(logic.values.source).toBe(DRAFT_CONFIG.source)
        expect(logic.values.isDirty).toBe(true)
    })

    it('marks a pending preview stale if the formula changes before the response arrives', async () => {
        let resolveResponse!: () => void
        const responseReady = new Promise<void>((resolve) => {
            resolveResponse = resolve
        })
        let resolveRequest!: () => void
        const requestStarted = new Promise<void>((resolve) => {
            resolveRequest = resolve
        })
        let body: unknown
        useMocks({
            post: {
                '/api/growth_enrichment_scoring/preview/': async ({ request }) => {
                    body = await request.json()
                    resolveRequest()
                    await responseReady
                    return PREVIEW
                },
            },
        })
        logic.actions.previewFormula()
        await requestStarted
        expect(logic.values.previewLoading).toBe(true)
        logic.actions.setSource(DRAFT_CONFIG.source)
        resolveResponse()
        await expectLogic(logic).toDispatchActions(['previewFormulaSuccess'])

        expect(body).toEqual({ source: ACTIVE_CONFIG.source, sample: 10, base_config_id: ACTIVE_CONFIG.id })
        expect(logic.values.preview?.response).toEqual(PREVIEW)
        expect(logic.values.previewIsStale).toBe(true)
        logic.actions.setSource(ACTIVE_CONFIG.source)
        expect(logic.values.previewIsStale).toBe(false)
    })

    it('previews the selected base and invalidates results when the base changes with the same formula', async () => {
        let body: unknown
        useMocks({
            post: {
                '/api/growth_enrichment_scoring/preview/': async ({ request }) => {
                    body = await request.json()
                    return PREVIEW
                },
            },
        })
        logic.actions.selectConfig({ ...DRAFT_CONFIG, source: ACTIVE_CONFIG.source })
        await expectLogic(logic, () => logic.actions.previewFormula()).toFinishAllListeners()
        expect(body).toEqual({ source: ACTIVE_CONFIG.source, sample: 10, base_config_id: DRAFT_CONFIG.id })
        expect(logic.values.previewIsStale).toBe(false)

        logic.actions.selectConfig(ACTIVE_CONFIG)
        expect(logic.values.previewIsStale).toBe(true)
    })

    it('marks a preview stale after the active version changes', async () => {
        useMocks({ post: { '/api/growth_enrichment_scoring/preview/': PREVIEW } })
        await expectLogic(logic, () => logic.actions.previewFormula()).toFinishAllListeners()
        expect(logic.values.previewIsStale).toBe(false)

        logic.actions.loadConfigsSuccess({
            results: [
                { ...ACTIVE_CONFIG, is_active: false },
                { ...DRAFT_CONFIG, is_active: true },
            ],
            default_source: ACTIVE_CONFIG.source,
        })
        expect(logic.values.previewIsStale).toBe(true)
        expect(logic.values.selectedConfig?.is_active).toBe(false)
    })
})
