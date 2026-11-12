import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { aeoSetupContext, aeoSetupCreate } from '../generated/api'
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
    keywords: 0,
    has_checks: false,
    ai_data_processing_approved: true,
    first_run_available: true,
    prompt_target: 20,
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
})
