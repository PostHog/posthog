import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { ApiError } from 'lib/api-error'

import { initKeaTests } from '~/test/init'

import {
    aeoPromptsOverview,
    aeoSetupCancel,
    aeoSetupContext,
    aeoSetupCreate,
    aeoSetupReset,
    aeoSetupRetrieve,
    aeoSetupStopChecks,
} from '../generated/api'
import type { AEOSetupContextApi, AEOSetupJobApi } from '../generated/api.schemas'
import { contentAutopilotSetupLogic } from './contentAutopilotSetupLogic'

jest.mock('../generated/api', () => ({
    aeoPromptsOverview: jest.fn(),
    aeoSetupContext: jest.fn(),
    aeoSetupCreate: jest.fn(),
    aeoSetupRetrieve: jest.fn(),
    aeoSetupStopChecks: jest.fn(),
    aeoSetupReset: jest.fn(),
    aeoSetupCancel: jest.fn(),
}))

const CONTEXT: AEOSetupContextApi = {
    websites: [{ domain: 'example.com', source: 'app_urls', pageviews: null }],
    own_domains: [],
    active_prompts: 0,
    max_active_prompts: 100,
    paused_prompts: 0,
    keywords: 0,
    has_checks: false,
    ai_data_processing_approved: true,
    first_run_available: true,
    prompt_target: 20,
    prompt_count_max: 50,
    website_days: 7,
    first_run_checks: [],
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
        // The wizard step persists per project, so one test's step must not open the next test's wizard.
        localStorage.clear()
        initKeaTests()
        jest.mocked(aeoSetupContext).mockResolvedValue(CONTEXT)
        jest.mocked(aeoSetupCreate).mockResolvedValue({ id: 'job', status: 'completed', steps: [], error: '' })
        logic = contentAutopilotSetupLogic()
        logic.mount()
    })

    afterEach(() => logic.unmount())

    it('sets up the best site on the onboarding engines that can run, and runs the first check', async () => {
        await expectLogic(logic).toDispatchActions(['loadSetupContextSuccess'])

        logic.actions.startSetup()

        await expectLogic(logic).toDispatchActions(['setJob'])
        expect(aeoSetupCreate).toHaveBeenCalledWith(String(MOCK_DEFAULT_TEAM.id), {
            domain: 'example.com',
            engines: ['claude-web-search'],
            run_first_check: true,
            prompt_count: 20,
        })
        expect(logic.values.wizardStep).toBe('review')
    })

    it('a first run skipped while setup saves prompts opens the first results once the backend says no run is left', async () => {
        await expectLogic(logic).toDispatchActions(['loadSetupContextSuccess'])
        jest.mocked(aeoSetupCreate).mockResolvedValue({ id: 'job', status: 'pending', steps: [], error: '' })
        jest.mocked(aeoSetupRetrieve).mockResolvedValue({
            id: 'job',
            status: 'completed',
            steps: [{ step: 'first_run', status: 'done', added: 0, detail: '' }],
            error: '',
        })
        logic.actions.startSetup()
        await expectLogic(logic).toDispatchActions(['setJob'])

        logic.actions.stopChecks()
        await expectLogic(logic).toDispatchActions(['stopChecksSuccess'])
        logic.actions.loadJob()
        await expectLogic(logic).toDispatchActions(['setJob']).toFinishAllListeners()

        expect(aeoSetupStopChecks).toHaveBeenCalledWith(String(MOCK_DEFAULT_TEAM.id))
        expect(logic.values.firstChecksWatching).toBe(false)
        expect(logic.values.wizardStep).toBe('results')
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

    it('reloads the prompt count when setup saves active prompts', async () => {
        await expectLogic(logic).toDispatchActions(['loadSetupContextSuccess'])
        jest.mocked(aeoSetupCreate).mockResolvedValue({ id: 'job', status: 'pending', steps: [], error: '' })
        jest.mocked(aeoSetupRetrieve).mockResolvedValue({
            id: 'job',
            status: 'completed',
            steps: [{ step: 'prompts', status: 'done', added: 20, detail: '' }],
            error: '',
        })
        jest.mocked(aeoSetupContext).mockResolvedValue({ ...CONTEXT, active_prompts: 20 })

        logic.actions.startSetup()
        await expectLogic(logic).toDispatchActions(['setJob'])
        logic.actions.loadJob()

        await expectLogic(logic).toDispatchActions(['setJob', 'loadSetupContextSuccess'])
        expect(logic.values.setupContext?.active_prompts).toBe(20)
    })

    it('follows the job already running when setup is refused with a conflict', async () => {
        await expectLogic(logic).toDispatchActions(['loadSetupContextSuccess'])
        jest.mocked(aeoSetupCreate).mockRejectedValue(
            new ApiError('conflict', 409, undefined, { detail: 'Setup is already running.', job_id: 'running' })
        )
        jest.mocked(aeoSetupRetrieve).mockResolvedValue({ id: 'running', status: 'pending', steps: [], error: '' })

        logic.actions.startSetup()

        await expectLogic(logic).toDispatchActions(['followJob', 'setJob'])
        expect(logic.values.jobRef?.id).toBe('running')
        expect(logic.values.startError).toBeNull()
    })

    it.each([
        ['drops a finished job whose checks never started', 'skipped', null],
        ['keeps a finished job whose checks are running', 'done', 'job'],
    ])('after a reload %s', async (_name, firstRunStatus, expectedJobId) => {
        const finished: AEOSetupJobApi = {
            id: 'job',
            status: 'completed',
            steps: [
                { step: 'first_run', status: firstRunStatus as 'skipped' | 'done', added: 0, detail: 'not_available' },
            ],
            error: '',
        }
        jest.mocked(aeoSetupRetrieve).mockResolvedValue(finished)
        logic.actions.setJobRef({ id: 'job', teamId: MOCK_DEFAULT_TEAM.id, onlyFirstRun: true, startedAt: Date.now() })
        logic.unmount()

        logic = contentAutopilotSetupLogic()
        logic.mount()

        await expectLogic(logic).toDispatchActions(['loadJob']).toFinishAllListeners()
        expect(logic.values.job?.id ?? null).toBe(expectedJobId)
        expect(logic.values.jobRef?.id ?? null).toBe(expectedJobId)
    })

    it('follows the first run until the backend says it has ended, then opens the first results', async () => {
        const running = { ...CONTEXT, active_prompts: 2, own_domains: ['example.com'], checks_running: true }
        jest.mocked(aeoSetupContext).mockResolvedValue({
            ...running,
            first_run_checks: [{ engine: 'claude-web-search', checks: 2 }],
        })
        await expectLogic(logic, () => logic.actions.loadSetupContext()).toDispatchActions(['loadSetupContextSuccess'])

        logic.actions.watchFirstChecks()
        await expectLogic(logic).toDispatchActions(['loadSetupContextSuccess']).toFinishAllListeners()
        expect(logic.values.firstChecksWatching).toBe(true)
        expect(logic.values.engineProgress).toEqual([{ engine: 'claude-web-search', done: 2, expected: 2 }])

        jest.mocked(aeoSetupContext).mockResolvedValue({ ...running, checks_running: false })
        logic.actions.pollFirstChecks(Date.now() + 60_000)
        await expectLogic(logic).toDispatchActions(['finishFirstChecks']).toFinishAllListeners()
        expect(logic.values.firstChecksWatching).toBe(false)
        expect(logic.values.wizardStep).toBe('results')
    })

    it('does not ask for the context again while the last read is still in flight', async () => {
        await expectLogic(logic).toDispatchActions(['loadSetupContextSuccess'])
        const running = { ...CONTEXT, checks_running: true }
        let release: (value: typeof running) => void = () => {}
        jest.mocked(aeoSetupContext).mockClear()
        jest.mocked(aeoSetupContext).mockImplementation(() => new Promise((resolve) => (release = resolve)))

        logic.actions.pollFirstChecks(Date.now() + 60_000)
        logic.actions.pollFirstChecks(Date.now() + 60_000)
        expect(aeoSetupContext).toHaveBeenCalledTimes(1)

        release(running)
        await expectLogic(logic).toDispatchActions(['loadSetupContextSuccess'])
        logic.actions.pollFirstChecks(Date.now() + 60_000)
        expect(aeoSetupContext).toHaveBeenCalledTimes(2)
    })

    it('cancelling setup keeps the step on what it saved instead of moving on', async () => {
        await expectLogic(logic).toDispatchActions(['loadSetupContextSuccess'])
        jest.mocked(aeoSetupCreate).mockResolvedValue({ id: 'job', status: 'pending', steps: [], error: '' })
        jest.mocked(aeoSetupCancel).mockResolvedValue({
            id: 'job',
            status: 'cancelled',
            steps: [{ step: 'prompts', status: 'skipped', added: 0, detail: 'cancelled' }],
            error: '',
        })
        logic.actions.startSetup()
        await expectLogic(logic).toDispatchActions(['setJob'])

        logic.actions.cancelSetup()
        await expectLogic(logic).toDispatchActions(['setJob']).toFinishAllListeners()

        expect(aeoSetupCancel).toHaveBeenCalledWith(String(MOCK_DEFAULT_TEAM.id), 'job')
        expect(logic.values.job?.status).toBe('cancelled')
        expect(logic.values.wizardStep).toBe('review')
    })

    it.each([
        ['checks of archived prompts from before a restart', [], false],
        ['checks of the prompts that are on', [{ engine: 'claude-web-search', checks: 3 }], true],
    ])('counts as a first check only %s', async (_name, firstRunChecks, expected) => {
        jest.mocked(aeoSetupContext).mockResolvedValue({
            ...CONTEXT,
            has_checks: true,
            first_run_checks: firstRunChecks,
        })
        await expectLogic(logic, () => logic.actions.loadSetupContext()).toDispatchActions(['loadSetupContextSuccess'])

        expect(logic.values.hasCurrentChecks).toBe(expected)
    })

    it.each([
        ['while setup runs, cancels it and stops its checks first', 'pending', true, true],
        ['once it is done, goes straight back', 'completed', false, false],
    ])('starting again %s', async (_name, jobStatus, checksRunning, stopsFirst) => {
        jest.mocked(aeoSetupContext).mockResolvedValue({
            ...CONTEXT,
            active_prompts: 20,
            own_domains: ['example.net'],
            checks_running: checksRunning,
        })
        await expectLogic(logic, () => logic.actions.loadSetupContext()).toDispatchActions(['loadSetupContextSuccess'])
        jest.mocked(aeoSetupCreate).mockResolvedValue({
            id: 'job',
            status: jobStatus as 'pending',
            steps: [],
            error: '',
        })
        logic.actions.startSetup()
        await expectLogic(logic).toDispatchActions(['setJob'])

        logic.actions.startAgain()
        await expectLogic(logic).toDispatchActions(['restartSetupDone']).toFinishAllListeners()

        expect(jest.mocked(aeoSetupCancel).mock.calls.length > 0).toBe(stopsFirst)
        expect(jest.mocked(aeoSetupStopChecks).mock.calls.length > 0).toBe(stopsFirst)
        if (stopsFirst) {
            expect(jest.mocked(aeoSetupCancel).mock.invocationCallOrder[0]).toBeLessThan(
                jest.mocked(aeoSetupReset).mock.invocationCallOrder[0]
            )
        }
        expect(aeoSetupReset).toHaveBeenCalled()
        expect(logic.values.wizardStep).toBe('website')
    })

    it.each([
        ['an ended run is dropped and the step stays put', false, 'review', null],
        ['a run still going is followed', true, 'review', 'job'],
    ])('after a reload, %s', async (_name, checksRunning, expectedStep, expectedJob) => {
        jest.mocked(aeoSetupContext).mockResolvedValue({
            ...CONTEXT,
            active_prompts: 5,
            has_checks: true,
            first_run_checks: [{ engine: 'claude-web-search', checks: 5 }],
            checks_running: checksRunning,
        })
        await expectLogic(logic, () => logic.actions.loadSetupContext()).toDispatchActions(['loadSetupContextSuccess'])
        logic.actions.setWizardStep('review')
        logic.actions.setJobRef({ id: 'job', teamId: MOCK_DEFAULT_TEAM.id, onlyFirstRun: false, startedAt: Date.now() })
        logic.actions.setJob({
            id: 'job',
            status: 'completed',
            steps: [{ step: 'first_run', status: 'done', added: 0, detail: '' }],
            error: '',
        })

        logic.actions.resumeFirstChecks()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.wizardStep).toBe(expectedStep)
        expect(logic.values.job?.id ?? null).toBe(expectedJob)
    })

    it('starting again returns to the website step with the old site in the field', async () => {
        jest.mocked(aeoSetupContext).mockResolvedValue({ ...CONTEXT, active_prompts: 20, own_domains: ['example.org'] })
        await expectLogic(logic, () => logic.actions.loadSetupContext()).toDispatchActions(['loadSetupContextSuccess'])
        logic.actions.setWizardStep('review')
        jest.mocked(aeoSetupContext).mockResolvedValue({
            ...CONTEXT,
            websites: [],
            has_checks: true,
            active_prompts: 1,
        })

        logic.actions.restartSetup()
        await expectLogic(logic).toDispatchActions(['restartSetupDone']).toFinishAllListeners()

        expect(aeoSetupReset).toHaveBeenCalledWith(String(MOCK_DEFAULT_TEAM.id))
        expect(logic.values.wizardStep).toBe('website')
        expect(logic.values.domain).toBe('example.org')
    })

    it.each([
        ['the website step for a new project', { has_checks: false }, false, 'website'],
        ['the review for prompts that never ran', { has_checks: false, active_prompts: 20 }, false, 'review'],
        ['the review while the first check runs', { has_checks: true, active_prompts: 20 }, true, 'review'],
        ['no wizard once results are in', { has_checks: true, active_prompts: 20 }, false, null],
    ])('opens %s', async (_name, context, watching, expected) => {
        jest.mocked(aeoSetupContext).mockResolvedValue({ ...CONTEXT, ...context })
        jest.mocked(aeoPromptsOverview).mockReturnValue(new Promise(() => {}))
        await expectLogic(logic, () => logic.actions.loadSetupContext()).toDispatchActions(['loadSetupContextSuccess'])
        if (watching) {
            logic.actions.watchFirstChecks()
        }
        expect(logic.values.wizardStep).toBe(expected)
        expect(logic.values.onboarding).toBe(expected !== null)
    })
})
