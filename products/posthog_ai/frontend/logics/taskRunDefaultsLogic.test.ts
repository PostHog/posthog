import { initKeaTests } from '~/test/init'

import { tasksMeConfigList } from 'products/tasks/frontend/generated/api'
import type { TasksResolvedAIRunDefaultsApi } from 'products/tasks/frontend/generated/api.schemas'

import { taskRunDefaultsLogic } from './taskRunDefaultsLogic'

jest.mock('products/tasks/frontend/generated/api', () => ({
    tasksMeConfigList: jest.fn(),
}))

describe('taskRunDefaultsLogic', () => {
    let logic: ReturnType<typeof taskRunDefaultsLogic.build>

    const ACP_DEFAULT: TasksResolvedAIRunDefaultsApi = {
        runtime: 'acp',
        runtime_adapter: 'codex',
        model: 'gpt-5.5',
        reasoning_effort: 'medium',
        source: 'user',
    }
    const PI_DEFAULT: TasksResolvedAIRunDefaultsApi = {
        runtime: 'pi',
        runtime_adapter: null,
        model: 'gpt-5.6-terra',
        reasoning_effort: 'off',
        source: 'user',
    }

    async function mountWithResolved(resolved: TasksResolvedAIRunDefaultsApi): Promise<void> {
        ;(tasksMeConfigList as jest.Mock).mockResolvedValue({
            ai_run_preferences: {},
            resolved_ai_run_defaults: resolved,
        })
        logic = taskRunDefaultsLogic()
        logic.mount()
        await logic.asyncActions.loadMyConfig()
    }

    beforeEach(() => {
        initKeaTests()
        jest.clearAllMocks()
    })

    afterEach(() => {
        logic?.unmount()
    })

    it('carries an ACP default through to the composer values', async () => {
        await mountWithResolved(ACP_DEFAULT)

        expect(logic.values.defaultModel).toBe('gpt-5.5')
        expect(logic.values.defaultEffort).toBe('medium')
        expect(logic.values.defaultRuntimeAdapter).toBe('codex')
    })

    // The web composer only drives the ACP harness. Passing a Pi model on would launch a web run on
    // whichever adapter the client catalogue guesses for it, which is a model the person never picked.
    it('reads a Pi default as no default for the web composer, while still reporting it', async () => {
        await mountWithResolved(PI_DEFAULT)

        expect(logic.values.defaultModel).toBeNull()
        expect(logic.values.defaultEffort).toBeNull()
        expect(logic.values.defaultRuntimeAdapter).toBeNull()
        // The settings page reads the raw resolution to name the harness it resolved to.
        expect(logic.values.resolvedDefaults).toEqual(PI_DEFAULT)
    })
})
