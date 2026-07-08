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
})
