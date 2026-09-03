import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { DEFAULT_HEADLINES } from '../components/welcome/welcomeDefaults'
import { taskTrackerSceneLogic } from '../scenes/TaskTracker/taskTrackerSceneLogic'
import { welcomeOverrideLogic } from './welcomeOverrideLogic'

describe('welcomeOverrideLogic', () => {
    let overrideLogic: ReturnType<typeof welcomeOverrideLogic.build>
    let trackerLogic: ReturnType<typeof taskTrackerSceneLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team/tasks/': { results: [], count: 0 },
                '/api/projects/:team/tasks/repositories/': { repositories: [] },
                '/api/environments/:team/integrations/': { results: [] },
            },
        })
        initKeaTests()
        overrideLogic = welcomeOverrideLogic()
        overrideLogic.mount()
        trackerLogic = taskTrackerSceneLogic({ panelId: 'max-side-panel' })
        trackerLogic.mount()
    })

    afterEach(() => {
        trackerLogic?.unmount()
        overrideLogic?.unmount()
    })

    // A scene that registers contextual headlines (e.g. the workflow editor) must win over the generic
    // defaults, and must stop winning once it deregisters (navigating away) — otherwise the /tasks
    // composer keeps showing another scene's headline.
    it('overrides the composer headline while registered and falls back on deregister', async () => {
        await expectLogic(overrideLogic, () => {
            overrideLogic.actions.registerHeadlines('scene', ['How can I help with this workflow?'])
        }).toFinishAllListeners()
        expect(trackerLogic.values.displayHeadline).toBe('How can I help with this workflow?')

        await expectLogic(overrideLogic, () => {
            overrideLogic.actions.deregisterHeadlines('scene')
        }).toFinishAllListeners()
        expect(DEFAULT_HEADLINES).toContain(trackerLogic.values.displayHeadline)
    })
})
