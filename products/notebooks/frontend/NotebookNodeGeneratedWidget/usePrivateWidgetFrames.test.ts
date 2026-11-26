import { act, renderHook } from '@testing-library/react'

import type { WidgetFrameApi } from '../generated/api.schemas'
import { usePrivateWidgetFrames } from './usePrivateWidgetFrames'

const frame: WidgetFrameApi = {
    sourceNodeId: 'capacity',
    name: 'shifts',
    runId: '6ea91fd8-cc4e-4d66-b596-5e409d6ef677',
    columns: [{ name: 'shifts', type: 'int64' }],
    rows: [[5], [8]],
    offset: 0,
    includedRowCount: 2,
    totalRowCount: 2,
    nextOffset: null,
    truncated: false,
}

it('runs on demand, pages the same private result, and clears data when a widget version changes', async () => {
    const compute = jest.fn().mockResolvedValue(frame)
    const { result, rerender } = renderHook(
        ({ version, inputs }) => usePrivateWidgetFrames(version, { key: inputs, compute }),
        { initialProps: { version: 'first', inputs: '240' } }
    )
    expect(compute).not.toHaveBeenCalled()
    await act(() => result.current.run(['shifts']))
    expect(result.current.page('shifts', 0, 1)).toMatchObject({ rows: [[5]], nextOffset: 1, runId: frame.runId })
    expect(result.current.page('shifts', 1, 1)).toMatchObject({ rows: [[8]], nextOffset: null, runId: frame.runId })
    expect(result.current.page('undeclared', 0, 1)).toBeUndefined()
    rerender({ version: 'first', inputs: '360' })
    expect(result.current.status).toContain('Inputs changed')
    expect(compute).toHaveBeenCalledTimes(1)
    rerender({ version: 'second', inputs: '360' })
    expect(result.current.page('shifts', 0, 1)).toBeUndefined()
    expect(result.current.status).toBeUndefined()
})
