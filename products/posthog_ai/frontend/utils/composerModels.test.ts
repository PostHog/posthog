import {
    ClaudeTaskRunCreateSchemaApi,
    CodexTaskRunCreateSchemaInitialPermissionModeEnumApi,
    InitialPermissionModeEnumApi,
    ModelChoiceApi,
    ReasoningEffortEnumApi,
    RuntimeAdapterEnumApi,
} from 'products/tasks/frontend/generated/api.schemas'

import {
    buildRunCreateRequest,
    getCapabilityLadder,
    listRuntimeAdapters,
    modelsForRuntimeAdapter,
} from './composerModels'
import { type PermissionMode } from './composerModes'

describe('composerModels', () => {
    const CATALOGUE: ModelChoiceApi[] = [
        {
            runtime_adapter: 'claude',
            model: 'claude-opus-4-8',
            display_name: 'Claude Opus 4.8',
            supported_efforts: ['low', 'medium', 'high'],
        },
        {
            runtime_adapter: 'codex',
            model: 'gpt-5.6-luna',
            display_name: 'GPT-5.6 Luna',
            supported_efforts: ['low', 'medium', 'high'],
        },
    ]

    // The runtime follows from the model, so a Codex pick must not launch on the Claude adapter — and each
    // runtime validates permission modes against its own vocabulary, so `bypassPermissions` has to become
    // `full-access` on the way out. Getting either wrong is a request the backend rejects.
    it.each([
        ['claude-opus-4-8', 'claude', InitialPermissionModeEnumApi.BypassPermissions],
        ['gpt-5.6-luna', 'codex', CodexTaskRunCreateSchemaInitialPermissionModeEnumApi.FullAccess],
    ])('%s launches on %s', (model, expectedAdapter, expectedMode) => {
        const request = buildRunCreateRequest(
            CATALOGUE,
            model,
            ReasoningEffortEnumApi.High,
            InitialPermissionModeEnumApi.BypassPermissions as PermissionMode,
            { branch: 'main' }
        )

        expect(request).toMatchObject({
            runtime_adapter: expectedAdapter,
            model,
            initial_permission_mode: expectedMode,
            branch: 'main',
        })
    })

    // A model absent from the catalogue (still loading, or retired from the gateway) must still produce a
    // sendable request rather than an undefined adapter.
    it('falls back to the claude adapter for an unknown model', () => {
        const request = buildRunCreateRequest(
            CATALOGUE,
            'some-unreleased-model',
            ReasoningEffortEnumApi.High,
            InitialPermissionModeEnumApi.Auto as PermissionMode,
            {}
        )

        expect(request).toMatchObject({ runtime_adapter: 'claude' })
    })

    // Some models take no reasoning effort at all, and the backend rejects any value for them
    // ("Supported values: none"). The composer always holds an effort for display, so the request has to drop it.
    it('omits the effort for a model that takes none', () => {
        const request = buildRunCreateRequest(
            [
                ...CATALOGUE,
                {
                    runtime_adapter: 'claude',
                    model: 'moonshotai/kimi-k3',
                    display_name: 'Moonshotai Kimi K3',
                    supported_efforts: [],
                },
            ],
            'moonshotai/kimi-k3',
            ReasoningEffortEnumApi.High,
            InitialPermissionModeEnumApi.Plan as PermissionMode,
            {}
        )

        expect((request as ClaudeTaskRunCreateSchemaApi).reasoning_effort).toBeUndefined()
    })

    // Every rung the Faster/Smarter slider offers has to be sendable. The ladder is a hardcoded progression, so a
    // model the gateway has retired — or one that no longer takes the paired effort — must drop out of the stops
    // rather than become a notch whose run the backend rejects.
    it('keeps only the ladder rungs the catalogue still serves', () => {
        const catalogue: ModelChoiceApi[] = [
            {
                runtime_adapter: 'claude',
                model: 'claude-sonnet-5',
                display_name: 'Claude Sonnet 5',
                supported_efforts: ['low', 'medium'],
            },
            {
                runtime_adapter: 'claude',
                model: 'claude-opus-5',
                display_name: 'Claude Opus 5',
                supported_efforts: ['medium', 'high', 'xhigh'],
            },
        ]

        // Dropped: sonnet at `high` (unsupported effort) and fable entirely (absent from the catalogue).
        expect(getCapabilityLadder(catalogue, RuntimeAdapterEnumApi.Claude)).toEqual([
            { model: 'claude-sonnet-5', effort: ReasoningEffortEnumApi.Medium },
            { model: 'claude-opus-5', effort: ReasoningEffortEnumApi.Medium },
            { model: 'claude-opus-5', effort: ReasoningEffortEnumApi.Xhigh },
        ])
        expect(getCapabilityLadder(catalogue, RuntimeAdapterEnumApi.Codex)).toEqual([])
    })

    // The picker groups by harness and offers one row per runtime, so both have to come off the catalogue rather
    // than a hardcoded list — a runtime the gateway stops serving must stop being offered.
    it("derives the harness list and each harness's models from the catalogue", () => {
        expect(listRuntimeAdapters(CATALOGUE)).toEqual(['claude', 'codex'])
        expect(modelsForRuntimeAdapter(CATALOGUE, RuntimeAdapterEnumApi.Codex).map((o) => o.model)).toEqual([
            'gpt-5.6-luna',
        ])
    })
})
