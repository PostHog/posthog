import { MOCK_DEFAULT_ORGANIZATION } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { phaiSidePanelComposerSeedLogic } from 'scenes/max/phaiSidePanelComposerSeedLogic'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { SidePanelTab } from '~/types'

import { taskTrackerSceneLogic } from 'products/posthog_ai/frontend/scenes/TaskTracker/taskTrackerSceneLogic'

import { SCOUT_AI_PANEL, scoutAiLogic } from './scoutAiLogic'

describe('scoutAiLogic', () => {
    let logic: ReturnType<typeof scoutAiLogic.build>
    let trackerLogic: ReturnType<typeof taskTrackerSceneLogic.build>
    let seedBridgeLogic: ReturnType<typeof phaiSidePanelComposerSeedLogic.build>
    let createdDescriptions: string[]

    beforeEach(() => {
        createdDescriptions = []
        useMocks({
            get: {
                '/api/projects/:team/tasks/': { results: [], count: 0 },
                '/api/projects/:team/tasks/repositories/': { repositories: [] },
                '/api/projects/:team/integrations/': { results: [] },
            },
            post: {
                '/api/projects/:team/tasks/': async ({ request }) => {
                    const body = (await request.json()) as Record<string, any>
                    createdDescriptions.push(body.description)
                    return [200, { id: 'new-task', ...body }]
                },
                '/api/projects/:team/tasks/:id/run/': () => [200, { id: 'new-task', latest_run: { id: 'run-1' } }],
            },
        })
    })

    afterEach(() => {
        logic?.unmount()
        seedBridgeLogic?.unmount()
        trackerLogic?.unmount()
    })

    // The generic PostHog AI panel is open, so its seed bridge hears the `inbox-scout` option too.
    const mountWithOpenPanel = (approved: boolean): void => {
        useMocks({
            get: {
                '/api/organizations/@current/': () => [
                    200,
                    { ...MOCK_DEFAULT_ORGANIZATION, is_ai_data_processing_approved: approved },
                ],
            },
        })
        initKeaTests(true, undefined, undefined, {
            ...MOCK_DEFAULT_ORGANIZATION,
            is_ai_data_processing_approved: approved,
        })
        sidePanelStateLogic.mount()
        sidePanelStateLogic.actions.openSidePanel(SidePanelTab.Max)
        trackerLogic = taskTrackerSceneLogic({ panelId: 'max-side-panel' })
        trackerLogic.mount()
        seedBridgeLogic = phaiSidePanelComposerSeedLogic({ panelId: 'max-side-panel' })
        seedBridgeLogic.mount()
        logic = scoutAiLogic()
        logic.mount()
    }

    it('sends the question once and opens the scout panel', async () => {
        mountWithOpenPanel(true)

        logic.actions.askScout({ skillName: 'checkout-watcher', scoutName: 'Checkout watcher' }, ' Are you working? ')
        await expectLogic(trackerLogic).toFinishAllListeners()

        expect(createdDescriptions).toHaveLength(1)
        expect(createdDescriptions[0]).toContain('Are you working?')
        expect(sidePanelStateLogic.values.selectedTabOptions).toBe(SCOUT_AI_PANEL)
        expect(logic.values.scoutChatContext).toEqual({ skillName: 'checkout-watcher', scoutName: 'Checkout watcher' })
        // The panel option must not land in the composer as a second prompt.
        expect(trackerLogic.values.newTaskData.description).toBe('')
    })

    it('sends nothing without AI data processing consent', async () => {
        mountWithOpenPanel(false)

        logic.actions.askScout({ skillName: 'checkout-watcher', scoutName: 'Checkout watcher' }, 'Are you working?')
        await expectLogic(trackerLogic).toFinishAllListeners()

        expect(createdDescriptions).toHaveLength(0)
        expect(sidePanelStateLogic.values.selectedTabOptions).not.toBe(SCOUT_AI_PANEL)
    })
})
