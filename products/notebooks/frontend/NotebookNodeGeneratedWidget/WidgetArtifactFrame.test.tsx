import '@testing-library/jest-dom'

import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'

import { initKeaTests } from '~/test/init'

import type { WidgetFrameApi } from 'products/notebooks/frontend/generated/api.schemas'

import { NOTEBOOK_FRAME_KEY_PREFIX } from './widgetArtifactBridge'
import { WidgetArtifactFrame } from './WidgetArtifactFrame'

class TestMessagePort {
    close = jest.fn()
    postMessage = jest.fn()
    addEventListener = jest.fn()
    removeEventListener = jest.fn()
    start = jest.fn()
}

const nativeMessageChannel = globalThis.MessageChannel

function sendNotebookPort(iframe: HTMLIFrameElement, port: TestMessagePort): void {
    window.dispatchEvent(
        new MessageEvent('message', {
            data: { channel: 'posthog-canvas', type: 'notebook-connect' },
            source: iframe.contentWindow,
            ports: [port as unknown as MessagePort],
        })
    )
}

describe('WidgetArtifactFrame', () => {
    beforeEach(() => {
        initKeaTests()
        jest.useFakeTimers()
        jest.spyOn(HTMLIFrameElement.prototype, 'contentWindow', 'get').mockReturnValue(window)
    })

    afterEach(() => {
        cleanup()
        jest.runOnlyPendingTimers()
        jest.useRealTimers()
        jest.restoreAllMocks()
        Object.defineProperty(globalThis, 'MessageChannel', {
            configurable: true,
            value: nativeMessageChannel,
            writable: true,
        })
    })

    it('accepts the trusted bootstrap port once and closes it on unmount', () => {
        const port = new TestMessagePort()
        const { unmount } = render(
            <WidgetArtifactFrame
                artifactUrl="https://example.com/globe.html"
                allowedFrames={[]}
                onReadFrame={jest.fn()}
            />
        )
        const iframe = screen.getByTitle('Widget') as HTMLIFrameElement
        expect(iframe).toHaveAttribute('src', 'https://example.com/globe.html#theme=light')
        expect(iframe).not.toHaveAttribute('srcdoc')
        sendNotebookPort(iframe, port)

        expect(port.start).toHaveBeenCalledTimes(1)
        unmount()
        expect(port.close).toHaveBeenCalledTimes(1)
    })

    it('pins concurrent pages for one dataframe to the first resolved run', async () => {
        const firstFrame: WidgetFrameApi = {
            name: 'pandas_df',
            runId: '00000000-0000-0000-0000-000000000001',
            columns: [],
            rows: [],
            totalRowCount: 200,
            includedRowCount: 100,
            offset: 0,
            nextOffset: 100,
            truncated: true,
        }
        let resolveFirstFrame: (frame: WidgetFrameApi) => void = () => undefined
        const pendingFirstFrame = new Promise<WidgetFrameApi>((resolve) => {
            resolveFirstFrame = resolve
        })
        const onReadFrame = jest
            .fn()
            .mockImplementationOnce(() => pendingFirstFrame)
            .mockResolvedValue({ ...firstFrame, offset: 100, nextOffset: null, truncated: false })
        const port = new TestMessagePort()
        render(
            <WidgetArtifactFrame
                artifactUrl="https://example.com/globe.html"
                allowedFrames={['pandas_df']}
                onReadFrame={onReadFrame}
            />
        )
        sendNotebookPort(screen.getByTitle('Widget') as HTMLIFrameElement, port)
        const route = port.addEventListener.mock.calls[0][1] as (event: { data: unknown }) => Promise<void>

        const firstRequest = route({
            data: {
                channel: 'posthog-canvas',
                type: 'data-request',
                id: 'first',
                method: 'stateGet',
                payload: { key: `${NOTEBOOK_FRAME_KEY_PREFIX}pandas_df:0:100` },
            },
        })
        const secondRequest = route({
            data: {
                channel: 'posthog-canvas',
                type: 'data-request',
                id: 'second',
                method: 'stateGet',
                payload: { key: `${NOTEBOOK_FRAME_KEY_PREFIX}pandas_df:100:100` },
            },
        })
        await Promise.resolve()
        await Promise.resolve()
        expect(onReadFrame).toHaveBeenCalledTimes(1)

        resolveFirstFrame(firstFrame)
        await Promise.all([firstRequest, secondRequest])

        expect(onReadFrame).toHaveBeenNthCalledWith(2, 'pandas_df', 100, 100, firstFrame.runId, expect.any(AbortSignal))
    })

    it('deduplicates only in-flight requests for the same page', async () => {
        const resolvedFrame = {
            name: 'pandas_df',
            runId: '00000000-0000-0000-0000-000000000001',
            columns: [],
            rows: [],
            totalRowCount: 0,
            includedRowCount: 0,
            offset: 0,
            nextOffset: null,
            truncated: false,
        } satisfies WidgetFrameApi
        let resolveFrame: (frame: WidgetFrameApi) => void = () => undefined
        const pendingFrame = new Promise<WidgetFrameApi>((resolve) => {
            resolveFrame = resolve
        })
        const onReadFrame = jest.fn().mockReturnValueOnce(pendingFrame).mockResolvedValue(resolvedFrame)
        const port = new TestMessagePort()
        render(
            <WidgetArtifactFrame
                artifactUrl="https://example.com/globe.html"
                allowedFrames={['pandas_df']}
                onReadFrame={onReadFrame}
            />
        )
        sendNotebookPort(screen.getByTitle('Widget') as HTMLIFrameElement, port)
        const route = port.addEventListener.mock.calls[0][1] as (event: { data: unknown }) => Promise<void>
        const request = (id: string): Promise<void> =>
            route({
                data: {
                    channel: 'posthog-canvas',
                    type: 'data-request',
                    id,
                    method: 'stateGet',
                    payload: { key: `${NOTEBOOK_FRAME_KEY_PREFIX}pandas_df:0:100` },
                },
            })

        const firstRequest = request('first')
        const secondRequest = request('second')
        await Promise.resolve()
        await Promise.resolve()
        expect(onReadFrame).toHaveBeenCalledTimes(1)

        resolveFrame(resolvedFrame)
        await Promise.all([firstRequest, secondRequest])
        await request('third')

        expect(onReadFrame).toHaveBeenCalledTimes(2)
    })

    it('aborts active frame reads when unmounted', async () => {
        let requestSignal: AbortSignal | undefined
        const onReadFrame = jest.fn(
            (_name: string, _offset: number, _limit: number, _runId: string | undefined, signal: AbortSignal) => {
                requestSignal = signal
                return new Promise<WidgetFrameApi>((_, reject) => {
                    signal.addEventListener('abort', () => reject(new Error('Request aborted')))
                })
            }
        )
        const port = new TestMessagePort()
        const { unmount } = render(
            <WidgetArtifactFrame
                artifactUrl="https://example.com/globe.html"
                allowedFrames={['pandas_df']}
                onReadFrame={onReadFrame}
            />
        )
        sendNotebookPort(screen.getByTitle('Widget') as HTMLIFrameElement, port)
        const route = port.addEventListener.mock.calls[0][1] as (event: { data: unknown }) => Promise<void>
        const routing = route({
            data: {
                channel: 'posthog-canvas',
                type: 'data-request',
                id: 'first',
                method: 'stateGet',
                payload: { key: `${NOTEBOOK_FRAME_KEY_PREFIX}pandas_df:0:100` },
            },
        })
        await Promise.resolve()
        await Promise.resolve()

        unmount()
        await routing

        expect(requestSignal?.aborted).toBe(true)
        expect(port.removeEventListener).toHaveBeenCalledTimes(1)
    })

    it('does not reconnect after the artifact navigates', () => {
        const onArtifactUnavailable = jest.fn()
        const initialPort = new TestMessagePort()
        const navigatedPort = new TestMessagePort()
        render(
            <WidgetArtifactFrame
                artifactUrl="https://example.com/globe.html"
                allowedFrames={[]}
                onReadFrame={jest.fn()}
                onArtifactUnavailable={onArtifactUnavailable}
            />
        )
        const iframe = screen.getByTitle('Widget') as HTMLIFrameElement
        sendNotebookPort(iframe, initialPort)
        fireEvent.load(iframe)
        fireEvent.load(iframe)
        sendNotebookPort(iframe, navigatedPort)

        expect(initialPort.close).toHaveBeenCalledTimes(1)
        expect(navigatedPort.start).not.toHaveBeenCalled()
        expect(onArtifactUnavailable).toHaveBeenCalledTimes(1)
    })

    it('does not give a parent-created bridge to artifacts without the trusted bootstrap', () => {
        const messageChannel = jest.fn()
        Object.defineProperty(globalThis, 'MessageChannel', {
            configurable: true,
            value: messageChannel,
            writable: true,
        })
        const postMessage = jest.spyOn(window, 'postMessage').mockImplementation()
        render(
            <WidgetArtifactFrame
                artifactUrl="https://example.com/globe.html"
                allowedFrames={[]}
                onReadFrame={jest.fn()}
            />
        )

        fireEvent.load(screen.getByTitle('Widget'))

        expect(messageChannel).not.toHaveBeenCalled()
        expect(postMessage).not.toHaveBeenCalled()
    })

    it('reports an unavailable artifact when the trusted runtime does not render in time', () => {
        const onArtifactUnavailable = jest.fn()
        const port = new TestMessagePort()
        render(
            <WidgetArtifactFrame
                artifactUrl="https://example.com/globe.html"
                allowedFrames={[]}
                onReadFrame={jest.fn()}
                onArtifactUnavailable={onArtifactUnavailable}
            />
        )
        const iframe = screen.getByTitle('Widget') as HTMLIFrameElement
        sendNotebookPort(iframe, port)

        act(() => jest.advanceTimersByTime(20_000))
        expect(onArtifactUnavailable).toHaveBeenCalledTimes(1)
    })
})
