import type { WidgetFrameApi } from 'products/notebooks/frontend/generated/api.schemas'

import { NOTEBOOK_FRAME_KEY_PREFIX, createWidgetHostMessageRouter, readWidgetFrame } from './widgetArtifactBridge'

const frame: WidgetFrameApi = {
    name: 'pandas_df',
    columns: [{ name: 'lat', type: 'float64' }],
    rows: [[51.5]],
    totalRowCount: 1,
    includedRowCount: 1,
    offset: 0,
    nextOffset: null,
    truncated: false,
}

describe('widgetArtifactBridge', () => {
    it('serves bounded pages for dataframes allowed by the widget version', async () => {
        const loadFrame = jest.fn().mockResolvedValue(frame)

        await expect(
            readWidgetFrame(['pandas_df'], loadFrame, {
                key: `${NOTEBOOK_FRAME_KEY_PREFIX}pandas_df:10:250`,
            })
        ).resolves.toBe(frame)
        expect(loadFrame).toHaveBeenCalledWith('pandas_df', 10, 250)
        await expect(
            readWidgetFrame(['pandas_df'], loadFrame, {
                key: `${NOTEBOOK_FRAME_KEY_PREFIX}private_df:0:100`,
            })
        ).rejects.toThrow('not available')
    })

    it('rejects invalid page sizes', async () => {
        await expect(
            readWidgetFrame(['pandas_df'], jest.fn(), {
                key: `${NOTEBOOK_FRAME_KEY_PREFIX}pandas_df:0:501`,
            })
        ).rejects.toThrow('page is invalid')
    })

    it('rejects Canvas methods other than the frame shim', async () => {
        const responses: Record<string, unknown>[] = []
        const route = createWidgetHostMessageRouter(
            (message) => responses.push(message),
            () => ({ onDataRequest: jest.fn() })
        )

        await route({ channel: 'posthog-canvas', type: 'data-request', id: '1', method: 'query', payload: {} })

        expect(responses[0]).toMatchObject({ id: '1', ok: false })
    })

    it('bounds requests that never finish', async () => {
        jest.useFakeTimers()
        const responses: Record<string, unknown>[] = []
        const route = createWidgetHostMessageRouter(
            (message) => responses.push(message),
            () => ({ onDataRequest: () => new Promise(() => undefined) })
        )

        const routing = route({
            channel: 'posthog-canvas',
            type: 'data-request',
            id: '1',
            method: 'stateGet',
            payload: { key: `${NOTEBOOK_FRAME_KEY_PREFIX}pandas_df:0:100` },
        })
        await jest.advanceTimersByTimeAsync(30_000)
        await routing

        expect(responses[0]).toMatchObject({ id: '1', ok: false, error: 'Widget data request timed out' })
        jest.useRealTimers()
    })
})
