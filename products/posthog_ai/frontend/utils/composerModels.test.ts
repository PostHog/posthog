import {
    CodexTaskRunCreateSchemaInitialPermissionModeEnumApi,
    InitialPermissionModeEnumApi,
    ModelChoiceApi,
    ReasoningEffortEnumApi,
} from 'products/tasks/frontend/generated/api.schemas'

import { buildRunCreateRequest, listRuntimeAdapters, modelsForRuntimeAdapter } from './composerModels'
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

    // The picker groups by harness and offers one row per runtime, so both have to come off the catalogue rather
    // than a hardcoded list — a runtime the gateway stops serving must stop being offered.
    it("derives the harness list and each harness's models from the catalogue", () => {
        expect(listRuntimeAdapters(CATALOGUE)).toEqual(['claude', 'codex'])
        expect(modelsForRuntimeAdapter(CATALOGUE, 'codex').map((option) => option.model)).toEqual(['gpt-5.6-luna'])
        expect(modelsForRuntimeAdapter(CATALOGUE, 'bedrock')).toEqual([])
    })
})
