import { MOCK_DEFAULT_ORGANIZATION } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { phaiSidePanelComposerSeedLogic } from 'scenes/max/phaiSidePanelComposerSeedLogic'

import { SCOUT_AI_PANEL } from '~/layout/ai/aiPanelIds'
import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { SidePanelTab } from '~/types'

import { attachedContextLogic } from 'products/posthog_ai/frontend/api/logics'
import { taskTrackerSceneLogic } from 'products/posthog_ai/frontend/scenes/TaskTracker/taskTrackerSceneLogic'

import { scoutAiContextItems, scoutAiLogic } from './scoutAiLogic'

describe('scoutAiLogic', () => {
    let logic: ReturnType<typeof scoutAiLogic.build>
    let trackerLogic: ReturnType<typeof taskTrackerSceneLogic.build>
    let seedBridgeLogic: ReturnType<typeof phaiSidePanelComposerSeedLogic.build>
    let createdDescriptions: string[]
    let startedMessages: string[]
    let approved: boolean

    beforeEach(() => {
        createdDescriptions = []
        startedMessages = []
        approved = true
        useMocks({
            get: {
                '/api/organizations/@current/': () => [
                    200,
                    { ...MOCK_DEFAULT_ORGANIZATION, is_ai_data_processing_approved: approved },
                ],
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
                '/api/projects/:team/tasks/:id/run/': async ({ request }) => {
                    const body = (await request.json()) as Record<string, any>
                    startedMessages.push(body.pending_user_message)
                    return [200, { id: 'new-task', latest_run: { id: 'run-1' } }]
                },
            },
        })
    })

    afterEach(() => {
        logic?.unmount()
        seedBridgeLogic?.unmount()
        trackerLogic?.unmount()
    })

    // The generic PostHog AI panel is open, so its seed bridge hears the `inbox-scout` option too.
    const mountWithOpenPanel = (consent: boolean): void => {
        approved = consent
        initKeaTests(true, undefined, undefined, {
            ...MOCK_DEFAULT_ORGANIZATION,
            is_ai_data_processing_approved: consent,
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

        const context = { scoutId: 'scout-config-1', skillName: 'checkout-watcher', scoutName: 'Checkout watcher' }
        attachedContextLogic.actions.registerContext('scout-page', scoutAiContextItems(context))
        logic.actions.askScout(context, ' Are you working? ')
        await expectLogic(trackerLogic).toFinishAllListeners()

        expect(createdDescriptions).toHaveLength(1)
        expect(createdDescriptions[0]).toContain('Are you working?')
        expect(startedMessages).toHaveLength(1)
        expect(startedMessages[0]).toContain('inbox_scout scout-config-1')
        expect(startedMessages[0]).not.toContain('checkout-watcher')
        expect(startedMessages[0]).not.toContain('Checkout watcher')
        expect(sidePanelStateLogic.values.selectedTabOptions).toBe(SCOUT_AI_PANEL)
        expect(logic.values.scoutChatContext).toEqual(context)
        // The panel option must not land in the composer as a second prompt.
        expect(trackerLogic.values.newTaskData.description).toBe('')
    })

    it('sends nothing without AI data processing consent', async () => {
        mountWithOpenPanel(false)

        logic.actions.askScout(
            { scoutId: 'scout-config-1', skillName: 'checkout-watcher', scoutName: 'Checkout watcher' },
            'Are you working?'
        )
        await expectLogic(trackerLogic).toFinishAllListeners()

        expect(createdDescriptions).toHaveLength(0)
        expect(sidePanelStateLogic.values.selectedTabOptions).not.toBe(SCOUT_AI_PANEL)
    })
})
