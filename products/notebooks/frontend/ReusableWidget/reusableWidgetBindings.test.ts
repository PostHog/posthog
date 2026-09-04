import { convertHogToJS, execHog } from 'lib/hog'

import type { WidgetFrameApi } from 'products/notebooks/frontend/generated/api.schemas'

import { applyReusableWidgetBinding, getReusableWidgetInputBinding } from './reusableWidgetBindings'

jest.mock('lib/hog', () => ({ convertHogToJS: jest.fn(), execHog: jest.fn() }))

const sourceFrame: WidgetFrameApi = {
    name: 'orders',
    runId: '00000000-0000-0000-0000-000000000001',
    columns: [
        { name: 'plan_name', type: 'string' },
        { name: 'amount', type: 'float64' },
    ],
    rows: [['Enterprise', 500]],
    totalRowCount: 1,
    includedRowCount: 1,
    offset: 0,
    nextOffset: null,
    truncated: false,
}

describe('reusableWidgetBindings', () => {
    beforeEach(() => {
        jest.resetAllMocks()
    })

    it('renames a directly bound notebook dataframe to the logical contract slot', async () => {
        const result = await applyReusableWidgetBinding(sourceFrame, 'revenue', { source: 'orders' })

        expect(result).toEqual({ ...sourceFrame, name: 'revenue' })
        expect(execHog).not.toHaveBeenCalled()
    })

    it('runs compiled Hog in the bounded browser VM and rebuilds the output frame', async () => {
        jest.mocked(execHog).mockReturnValue({ finished: true, error: null, result: ['hog-result'] } as never)
        jest.mocked(convertHogToJS).mockReturnValue([{ plan: 'Enterprise', revenue: 500 }] as never)

        const result = await applyReusableWidgetBinding(sourceFrame, 'revenue', {
            source: 'orders',
            hog: 'return rows',
            bytecode: ['_H', 1],
        })

        expect(execHog).toHaveBeenCalledWith(
            ['_H', 1],
            expect.objectContaining({
                functions: {},
                maxAsyncSteps: 0,
                memoryLimit: 16 * 1024 * 1024,
                timeout: 100,
            })
        )
        expect(result).toEqual({
            ...sourceFrame,
            name: 'revenue',
            columns: [
                { name: 'plan', type: 'unknown' },
                { name: 'revenue', type: 'unknown' },
            ],
            rows: [['Enterprise', 500]],
            totalRowCount: 1,
            includedRowCount: 1,
            nextOffset: null,
            truncated: false,
        })
    })

    it('ignores malformed persisted bindings', () => {
        expect(getReusableWidgetInputBinding({ revenue: { source: 42 } }, 'revenue')).toBeUndefined()
    })

    it('preserves source pagination after mapping a page', async () => {
        jest.mocked(execHog).mockReturnValue({ finished: true, error: null, result: ['hog-result'] } as never)
        jest.mocked(convertHogToJS).mockReturnValue([{ revenue: 500 }] as never)

        const result = await applyReusableWidgetBinding(
            { ...sourceFrame, totalRowCount: 200, nextOffset: 100, truncated: true },
            'revenue',
            { source: 'orders', hog: 'return rows', bytecode: ['_H', 1] }
        )

        expect(result.totalRowCount).toBe(200)
        expect(result.nextOffset).toBe(100)
        expect(result.truncated).toBe(true)
    })

    it('rejects mapped rows that do not satisfy the reusable contract', async () => {
        jest.mocked(execHog).mockReturnValue({ finished: true, error: null, result: ['hog-result'] } as never)
        jest.mocked(convertHogToJS).mockReturnValue([{ amount: 500 }] as never)

        await expect(
            applyReusableWidgetBinding(
                sourceFrame,
                'revenue',
                { source: 'orders', hog: 'return rows', bytecode: ['_H', 1] },
                ['plan', 'revenue']
            )
        ).rejects.toThrow('must return the contract column "plan"')
    })
})
