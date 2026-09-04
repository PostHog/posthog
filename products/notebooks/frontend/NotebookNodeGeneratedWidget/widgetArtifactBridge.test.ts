import type { WidgetFrameApi } from 'products/notebooks/frontend/generated/api.schemas'

import { NOTEBOOK_FRAME_KEY_PREFIX, createWidgetHostMessageRouter, readWidgetFrame } from './widgetArtifactBridge'

const frame: WidgetFrameApi = {
    name: 'pandas_df',
    runId: '00000000-0000-0000-0000-000000000001',
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
        const signal = new AbortController().signal

        await expect(
            readWidgetFrame(
                ['pandas_df'],
                loadFrame,
                {
                    key: `${NOTEBOOK_FRAME_KEY_PREFIX}pandas_df:10:250`,
                },
                signal
            )
        ).resolves.toBe(frame)
        expect(loadFrame).toHaveBeenCalledWith('pandas_df', 10, 250, signal)
        await expect(
            readWidgetFrame(
                ['pandas_df'],
                loadFrame,
                {
                    key: `${NOTEBOOK_FRAME_KEY_PREFIX}pandas_df:0:5000`,
                },
                signal
            )
        ).resolves.toBe(frame)
        expect(loadFrame).toHaveBeenLastCalledWith('pandas_df', 0, 500, signal)
        await expect(
            readWidgetFrame(
                ['pandas_df'],
                loadFrame,
                {
                    key: `${NOTEBOOK_FRAME_KEY_PREFIX}private_df:0:100`,
                },
                signal
            )
        ).rejects.toThrow('not available')
    })

    it('rejects invalid page sizes', async () => {
        const signal = new AbortController().signal
        await expect(
            readWidgetFrame(
                ['pandas_df'],
                jest.fn(),
                {
                    key: `${NOTEBOOK_FRAME_KEY_PREFIX}pandas_df:0:0`,
                },
                signal
            )
        ).rejects.toThrow('page is invalid')
    })

    it('rejects Canvas methods other than the frame shim', async () => {
        const responses: Record<string, unknown>[] = []
        const { route } = createWidgetHostMessageRouter(
            (message) => responses.push(message),
            () => ({ onDataRequest: jest.fn() })
        )

        await route({ channel: 'posthog-canvas', type: 'data-request', id: '1', method: 'query', payload: {} })

        expect(responses[0]).toMatchObject({ id: '1', ok: false })
    })

    it('passes a bounded runtime error to the host', async () => {
        const onError = jest.fn()
        const { route } = createWidgetHostMessageRouter(jest.fn(), () => ({ onDataRequest: jest.fn(), onError }))

        await route({ channel: 'posthog-canvas', type: 'error', message: 'x'.repeat(1_000) })

        expect(onError).toHaveBeenCalledWith('x'.repeat(500))
    })

    it('caps the total work one artifact can request', async () => {
        const responses: Record<string, unknown>[] = []
        const onDataRequest = jest.fn().mockResolvedValue(frame)
        const onExhausted = jest.fn()
        const { route } = createWidgetHostMessageRouter(
            (message) => responses.push(message),
            () => ({ onDataRequest }),
            onExhausted
        )

        for (let index = 0; index < 201; index++) {
            await route({
                channel: 'posthog-canvas',
                type: 'data-request',
                id: String(index),
                method: 'stateGet',
                payload: { key: `${NOTEBOOK_FRAME_KEY_PREFIX}pandas_df:0:100` },
            })
        }

        expect(onDataRequest).toHaveBeenCalledTimes(200)
        expect(responses).toHaveLength(200)
        expect(onExhausted).toHaveBeenCalledTimes(1)
    })

    it('counts rejected requests toward the artifact limit', async () => {
        const responses: Record<string, unknown>[] = []
        const onDataRequest = jest.fn()
        const onExhausted = jest.fn()
        const { route } = createWidgetHostMessageRouter(
            (message) => responses.push(message),
            () => ({ onDataRequest }),
            onExhausted
        )

        for (let index = 0; index < 201; index++) {
            await route({
                channel: 'posthog-canvas',
                type: 'data-request',
                id: String(index),
                method: 'query',
                payload: {},
            })
        }

        expect(onDataRequest).not.toHaveBeenCalled()
        expect(responses).toHaveLength(200)
        expect(onExhausted).toHaveBeenCalledTimes(1)
    })

    it('bounds requests that never finish', async () => {
        jest.useFakeTimers()
        const responses: Record<string, unknown>[] = []
        const { route } = createWidgetHostMessageRouter(
            (message) => responses.push(message),
            () => ({
                onDataRequest: (_method, _payload, signal) =>
                    new Promise((_, reject) => {
                        signal.addEventListener('abort', () => reject(new Error('Request aborted')))
                    }),
            })
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

    it('releases request capacity when an aborted callback never settles', async () => {
        jest.useFakeTimers()
        const responses: Record<string, unknown>[] = []
        let requestCount = 0
        const { route } = createWidgetHostMessageRouter(
            (message) => responses.push(message),
            () => ({
                onDataRequest: () => {
                    requestCount += 1
                    return requestCount <= 8 ? new Promise(() => undefined) : Promise.resolve(frame)
                },
            })
        )
        const stalled = Array.from({ length: 8 }, (_, index) =>
            route({
                channel: 'posthog-canvas',
                type: 'data-request',
                id: `stalled-${index}`,
                method: 'stateGet',
                payload: { key: `${NOTEBOOK_FRAME_KEY_PREFIX}pandas_df:0:100` },
            })
        )

        await jest.advanceTimersByTimeAsync(30_000)
        await Promise.all(stalled)
        await route({
            channel: 'posthog-canvas',
            type: 'data-request',
            id: 'next',
            method: 'stateGet',
            payload: { key: `${NOTEBOOK_FRAME_KEY_PREFIX}pandas_df:0:100` },
        })

        expect(responses).toHaveLength(9)
        expect(responses.at(-1)).toEqual(expect.objectContaining({ id: 'next', ok: true, result: frame }))
        jest.useRealTimers()
    })

    it('aborts active requests when disposed', async () => {
        let requestSignal: AbortSignal | undefined
        const { route, dispose } = createWidgetHostMessageRouter(jest.fn(), () => ({
            onDataRequest: (_method, _payload, signal) => {
                requestSignal = signal
                return new Promise(() => undefined)
            },
        }))
        const routing = route({
            channel: 'posthog-canvas',
            type: 'data-request',
            id: '1',
            method: 'stateGet',
            payload: { key: `${NOTEBOOK_FRAME_KEY_PREFIX}pandas_df:0:100` },
        })
        await Promise.resolve()

        dispose()
        await routing

        expect(requestSignal?.aborted).toBe(true)
    })
})
