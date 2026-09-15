import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { reusableWidgetsDemoFrame, reusableWidgetsUpdateDemoData } from '../generated/api'
import type { ReusableWidgetVersionDetailApi, WidgetFrameApi } from '../generated/api.schemas'
import { reusableWidgetDemoDataLogic } from './reusableWidgetDemoDataLogic'

jest.mock('../generated/api', () => ({ reusableWidgetsDemoFrame: jest.fn(), reusableWidgetsUpdateDemoData: jest.fn() }))

const version = {
    id: '00000000-0000-4000-8000-000000000042',
    input_contract: [{ slot: 'revenue', columns: [{ name: 'plan', type: 'String' }] }],
} as ReusableWidgetVersionDetailApi
const frame = { name: 'revenue', columns: version.input_contract[0].columns, rows: [['Starter']] } as WidgetFrameApi

describe('reusableWidgetDemoDataLogic', () => {
    let logic: ReturnType<typeof reusableWidgetDemoDataLogic.build>
    const onSaved = jest.fn()
    beforeEach(async () => {
        initKeaTests()
        jest.clearAllMocks()
        jest.mocked(reusableWidgetsDemoFrame).mockResolvedValue(frame)
        logic = reusableWidgetDemoDataLogic({
            projectId: 1,
            widgetId: 'widget',
            version,
            canEdit: true,
            onClose: jest.fn(),
            onSaved,
        })
        await expectLogic(logic, () => {
            logic.mount()
        }).toFinishAllListeners()
    })
    afterEach(() => logic.unmount())

    it('saves the selected version and refreshes the displayed rows only after success', async () => {
        logic.actions.startEditing()
        logic.actions.setDraftJSON('[{"plan":"Growth"}]')
        let finishSave!: (saved: WidgetFrameApi) => void
        jest.mocked(reusableWidgetsUpdateDemoData).mockImplementation(
            () =>
                new Promise((resolve) => {
                    finishSave = resolve
                })
        )
        logic.actions.saveDemoData()
        expect(logic.values.savedFrameLoading).toBe(true)
        expect(logic.values.demoFrame?.rows).toEqual([['Starter']])
        await expectLogic(logic, () => finishSave({ ...frame, rows: [['Growth']] })).toFinishAllListeners()
        expect(reusableWidgetsUpdateDemoData).toHaveBeenCalledWith('1', 'widget', {
            version_id: version.id,
            frame_name: 'revenue',
            rows: [['Growth']],
        })
        expect(logic.values.demoFrame?.rows).toEqual([['Growth']])
        expect(logic.values.editing).toBe(false)
        expect(onSaved).toHaveBeenCalledTimes(1)
    })

    it('keeps edits after a failed save so they can be corrected or retried', async () => {
        jest.mocked(reusableWidgetsUpdateDemoData).mockRejectedValue(new Error('The selected version changed.'))
        logic.actions.startEditing()
        logic.actions.setDraftJSON('[{"plan":"Growth"}]')
        await expectLogic(logic, () => logic.actions.saveDemoData()).toFinishAllListeners()
        expect(logic.values.editing).toBe(true)
        expect(logic.values.draftJSON).toContain('Growth')
        expect(logic.values.saveError).toBe('The selected version changed.')
        expect(logic.values.savedFrameLoading).toBe(false)
        expect(onSaved).not.toHaveBeenCalled()
    })
})
