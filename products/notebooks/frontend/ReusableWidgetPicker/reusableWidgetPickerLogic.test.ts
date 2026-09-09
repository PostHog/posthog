import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { notebooksWidgetAttach, reusableWidgetsRetrieve } from '../generated/api'
import type { ReusableWidgetDetailApi, WidgetStatusApi } from '../generated/api.schemas'
import { reusableWidgetPickerLogic } from './reusableWidgetPickerLogic'

jest.mock('../generated/api', () => ({ notebooksWidgetAttach: jest.fn(), reusableWidgetsRetrieve: jest.fn() }))

const widget = {
    id: '00000000-0000-4000-8000-000000000042',
    current_version: {
        frame_names: ['revenue'],
        input_contract: [
            {
                slot: 'revenue',
                columns: [
                    { name: 'plan', type: 'String' },
                    { name: 'amount', type: 'Float64' },
                ],
            },
        ],
    },
} as ReusableWidgetDetailApi
const content = {
    type: 'doc',
    content: [
        {
            type: 'ph-python-v2',
            attrs: {
                nodeId: 'wrong',
                returnVariable: 'unrelated_df',
                result: { types: [['label', 'String']], row_count: 1 },
            },
        },
        {
            type: 'ph-python-v2',
            attrs: {
                nodeId: 'right',
                returnVariable: 'sales_df',
                result: {
                    types: [
                        ['plan', 'String'],
                        ['amount', 'Float64'],
                    ],
                    row_count: 1,
                },
            },
        },
    ],
}

describe('reusableWidgetPickerLogic', () => {
    let logic: ReturnType<typeof reusableWidgetPickerLogic.build>
    const onAttached = jest.fn()
    beforeEach(() => {
        initKeaTests()
        jest.clearAllMocks()
        jest.mocked(reusableWidgetsRetrieve).mockResolvedValue(widget)
        jest.mocked(notebooksWidgetAttach).mockResolvedValue({ widget_id: widget.id } as WidgetStatusApi)
        logic = reusableWidgetPickerLogic({
            projectId: 1,
            notebookShortId: 'sales-notebook',
            nodeId: 'chart',
            getContent: () => content,
            persistNotebook: async () => {},
            onAttached,
        })
        logic.mount()
    })
    afterEach(() => logic.unmount())

    it('selects a matching schema ahead of dataframe order and attaches without Hog', async () => {
        await expectLogic(logic, () => logic.actions.selectReusableWidget(widget.id)).toFinishAllListeners()
        expect(logic.values.resolvedBindings.revenue.source).toBe('sales_df')
        expect(logic.values.attachDisabledReason).toBeUndefined()
        await expectLogic(logic, () => logic.actions.attachReusableWidget()).toFinishAllListeners()
        expect(notebooksWidgetAttach).toHaveBeenCalledWith('1', 'sales-notebook', 'chart', {
            widget_id: widget.id,
            version_id: null,
            input_bindings: { revenue: { source: 'sales_df', hog: undefined, bytecode: undefined } },
        })
        expect(onAttached).toHaveBeenCalled()
    })

    it('clears old mappings when the source changes and blocks an incomplete connection', async () => {
        await expectLogic(logic, () => logic.actions.selectReusableWidget(widget.id)).toFinishAllListeners()
        logic.actions.setMappingMode('revenue', 'hog')
        logic.actions.setBindingHog('revenue', 'return rows')
        logic.actions.setAdvancedOpen('revenue', false)
        expect(logic.values.resolvedBindings.revenue.hog).toBe('return rows')
        logic.actions.setBindingSource('revenue', 'unrelated_df')
        expect(logic.values.resolvedBindings.revenue.hog).toBe('')
        expect(logic.values.attachDisabledReason).toContain('Match the columns')
        await expectLogic(logic, () => logic.actions.attachReusableWidget()).toFinishAllListeners()
        expect(notebooksWidgetAttach).not.toHaveBeenCalled()
    })
})
