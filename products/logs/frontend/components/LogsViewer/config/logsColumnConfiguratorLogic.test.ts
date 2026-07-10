import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { logsColumnConfiguratorLogic } from './logsColumnConfiguratorLogic'
import { logsViewerConfigLogic } from './logsViewerConfigLogic'

describe('logsColumnConfiguratorLogic', () => {
    let logic: ReturnType<typeof logsColumnConfiguratorLogic.build>
    let configLogic: ReturnType<typeof logsViewerConfigLogic.build>

    beforeEach(() => {
        localStorage.clear()
        initKeaTests()
        configLogic = logsViewerConfigLogic({ id: 'test-tab' })
        configLogic.mount()
        logic = logsColumnConfiguratorLogic({ id: 'test-tab' })
        logic.mount()
        logic.actions.openConfigurator()
    })

    afterEach(() => {
        logic.unmount()
        configLogic.unmount()
    })

    it('seeds the draft from current columns on open', () => {
        expect(logic.values.draft).toEqual(configLogic.values.columns)
    })

    it('draft edits do not touch the applied columns until applyDraft', async () => {
        const before = configLogic.values.columns
        logic.actions.addDraftColumn({ type: 'custom' })
        // Normalization pins message last, so the new custom column sits just before it
        const draftId = logic.values.draft.find((c) => c.type === 'custom')!.id
        logic.actions.updateDraftColumn(draftId, { expression: 'attributes.http.url' })

        // Still uncommitted — this is what keeps per-keystroke edits from firing logs queries
        expect(configLogic.values.columns).toEqual(before)

        await expectLogic(logic, () => {
            logic.actions.applyDraft()
        }).toFinishAllListeners()

        expect(configLogic.values.columns).toHaveLength(before.length + 1)
        expect(configLogic.values.columns.find((c) => c.type === 'custom')?.expression).toBe('attributes.http.url')
        // Message stays pinned last through apply
        expect(configLogic.values.columns.at(-1)?.type).toBe('message')
        expect(logic.values.isOpen).toBe(false)
    })

    it.each<[string, () => void, string]>([
        [
            'a custom column with no expression',
            () => logic.actions.addDraftColumn({ type: 'custom' }),
            'Custom columns need an expression',
        ],
        [
            'an empty column list',
            () => logic.values.draft.forEach((c) => logic.actions.removeDraftColumn(c.id)),
            'At least one column is required',
        ],
    ])('blocks apply for %s', async (_, mutate, error) => {
        const before = configLogic.values.columns
        mutate()
        expect(logic.values.draftErrors).toBe(error)

        await expectLogic(logic, () => {
            logic.actions.applyDraft()
        }).toFinishAllListeners()
        expect(configLogic.values.columns).toEqual(before)
    })

    it('moveDraftColumn reorders by index but keeps message pinned last', () => {
        logic.actions.addDraftColumn({ type: 'custom', expression: 'attributes.a' })
        // Draft is [timestamp, custom, message] after normalization
        const ids = logic.values.draft.map((c) => c.id)
        logic.actions.moveDraftColumn(0, 1)
        expect(logic.values.draft.map((c) => c.id)).toEqual([ids[1], ids[0], ids[2]])

        // Dragging a column onto/past message re-normalizes message back to the end
        logic.actions.moveDraftColumn(0, 2)
        expect(logic.values.draft.at(-1)?.type).toBe('message')
    })
})
