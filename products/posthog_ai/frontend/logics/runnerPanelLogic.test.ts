import { initKeaTests } from '~/test/init'

import { runnerPanelLogic } from './runnerPanelLogic'

describe('runnerPanelLogic', () => {
    let logic: ReturnType<typeof runnerPanelLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = runnerPanelLogic()
        logic.mount()
    })

    afterEach(() => {
        logic?.unmount()
    })

    // goBack must route to where the open task was launched from — history if the panel was showing the
    // history list, the composer otherwise — mirroring legacy Max's `backToScreen` memory. Guards against
    // either the "opened a task" listener losing that memory or `goBack` landing on the wrong screen.
    it('goBack from a task opened out of history returns to history, then to the composer', () => {
        logic.actions.setHistoryExpanded(true)
        logic.actions.setActiveCreation({ streamKey: 'run-1' })
        expect(logic.values.activeCreation).toEqual({ streamKey: 'run-1' })
        expect(logic.values.historyExpanded).toBe(false)

        logic.actions.goBack()
        expect(logic.values.activeCreation).toBe(null)
        expect(logic.values.historyExpanded).toBe(true)

        logic.actions.goBack()
        expect(logic.values.historyExpanded).toBe(false)
    })

    it('goBack from a task opened out of the composer lands directly on the composer', () => {
        logic.actions.setActiveCreation({ streamKey: 'run-1' })
        expect(logic.values.historyExpanded).toBe(false)

        logic.actions.goBack()
        expect(logic.values.activeCreation).toBe(null)
        expect(logic.values.historyExpanded).toBe(false)
    })

    // An embedded panel (Max's side panel) must survive a full page load: the open run is remembered
    // per browser tab and restored on remount, so following a link out of the chat doesn't lose it.
    describe('embedded-panel persistence across reloads', () => {
        const remount = (panelId?: string): ReturnType<typeof runnerPanelLogic.build> => {
            logic.unmount()
            initKeaTests()
            logic = runnerPanelLogic({ panelId })
            logic.mount()
            return logic
        }

        beforeEach(() => {
            sessionStorage.clear()
            logic.unmount()
            logic = runnerPanelLogic({ panelId: 'sidepanel' })
            logic.mount()
        })

        it('restores a bound run on a fresh mount and clears it when dismissed', () => {
            logic.actions.setActiveCreation({ streamKey: 'run-1', taskId: 'task-1', runId: 'run-1' })

            remount('sidepanel')
            expect(logic.values.activeCreation).toEqual({ streamKey: 'run-1', taskId: 'task-1', runId: 'run-1' })

            logic.actions.goBack()
            remount('sidepanel')
            expect(logic.values.activeCreation).toBe(null)
        })

        it('does not persist a pending creation that has no server run to rebind', () => {
            logic.actions.setActiveCreation({ streamKey: 'optimistic-1' })

            remount('sidepanel')
            expect(logic.values.activeCreation).toBe(null)
        })

        it('the scene singleton stays URL-driven and never restores from storage', () => {
            logic.actions.setActiveCreation({ streamKey: 'run-1', taskId: 'task-1', runId: 'run-1' })

            remount(undefined)
            expect(logic.values.activeCreation).toBe(null)
        })
    })
})
