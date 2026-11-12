import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { ApiError } from 'lib/api-error'

import { initKeaTests } from '~/test/init'

import { aeoSetupContext, aeoSetupCreate, aeoSetupRetrieve } from '../generated/api'
import type { AEOSetupContextApi } from '../generated/api.schemas'
import { contentAutopilotSetupLogic } from './contentAutopilotSetupLogic'

jest.mock('../generated/api', () => ({
    aeoSetupContext: jest.fn(),
    aeoSetupCreate: jest.fn(),
    aeoSetupRetrieve: jest.fn(),
}))

const CONTEXT: AEOSetupContextApi = {
    websites: [{ domain: 'example.com', source: 'app_urls', pageviews: null }],
    own_domains: [],
    active_prompts: 0,
    paused_prompts: 0,
    keywords: 0,
    has_checks: false,
    ai_data_processing_approved: true,
    first_run_available: true,
    prompt_target: 20,
    website_days: 7,
    engines: [
        { engine: 'claude-web-search', mode: 'web_search', available: true, enabled: true, frequency: 'daily' },
        { engine: 'perplexity-web-search', mode: 'web_search', available: false, enabled: true, frequency: 'daily' },
        { engine: 'exa-answer', mode: 'web_search', available: true, enabled: false, frequency: 'daily' },
    ],
}

describe('contentAutopilotSetupLogic', () => {
    let logic: ReturnType<typeof contentAutopilotSetupLogic.build>

    beforeEach(() => {
        jest.clearAllMocks()
        initKeaTests()
        jest.mocked(aeoSetupContext).mockResolvedValue(CONTEXT)
        jest.mocked(aeoSetupCreate).mockResolvedValue({ id: 'job', status: 'completed', steps: [], error: '' })
        logic = contentAutopilotSetupLogic()
        logic.mount()
    })

    afterEach(() => logic.unmount())

    it.each([
        ['configure only', false],
        ['set up and run once', true],
    ])('%s sends the best site, the available chosen engines and the run choice', async (_name, runFirstCheck) => {
        await expectLogic(logic).toDispatchActions(['loadSetupContextSuccess'])
        // Perplexity is on by default but cannot run here, so it is never sent.
        expect(logic.values.selectedEngines).toEqual(['claude-web-search'])

        logic.actions.toggleEngine('exa-answer', true)
        logic.actions.startSetup(runFirstCheck)

        await expectLogic(logic).toDispatchActions(['setJob'])
        expect(aeoSetupCreate).toHaveBeenCalledWith(String(MOCK_DEFAULT_TEAM.id), {
            domain: 'example.com',
            engines: ['claude-web-search', 'exa-answer'],
            run_first_check: runFirstCheck,
        })
    })

    it.each([
        ['runs the active prompts', false],
        ['turns the paused prompts on, then runs them', true],
    ])('a first run %s without sending a site or engines', async (_name, activatePaused) => {
        await expectLogic(logic).toDispatchActions(['loadSetupContextSuccess'])

        logic.actions.startFirstRun(activatePaused)

        await expectLogic(logic).toDispatchActions(['setJob'])
        expect(aeoSetupCreate).toHaveBeenCalledWith(String(MOCK_DEFAULT_TEAM.id), {
            only_first_run: true,
            activate_paused_prompts: activatePaused,
        })
        expect(logic.values.jobRef?.onlyFirstRun).toBe(true)
    })

    it('follows the job already running when setup is refused with a conflict', async () => {
        await expectLogic(logic).toDispatchActions(['loadSetupContextSuccess'])
        jest.mocked(aeoSetupCreate).mockRejectedValue(
            new ApiError('conflict', 409, undefined, { detail: 'Setup is already running.', job_id: 'running' })
        )
        jest.mocked(aeoSetupRetrieve).mockResolvedValue({ id: 'running', status: 'pending', steps: [], error: '' })

        logic.actions.startSetup(false)

        await expectLogic(logic).toDispatchActions(['followJob', 'setJob'])
        expect(logic.values.jobRef?.id).toBe('running')
        expect(logic.values.startError).toBeNull()
    })
})
