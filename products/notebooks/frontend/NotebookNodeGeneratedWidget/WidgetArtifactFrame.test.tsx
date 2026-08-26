import '@testing-library/jest-dom'

import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'

import { initKeaTests } from '~/test/init'

import { WidgetArtifactFrame } from './WidgetArtifactFrame'

class TestMessagePort {
    close = jest.fn()
    postMessage = jest.fn()
    addEventListener = jest.fn()
    start = jest.fn()
}

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
        const iframe = screen.getByTitle('Generated widget') as HTMLIFrameElement
        expect(iframe).toHaveAttribute('src', 'https://example.com/globe.html#theme=light')
        expect(iframe).not.toHaveAttribute('srcdoc')
        sendNotebookPort(iframe, port)

        expect(port.start).toHaveBeenCalledTimes(1)
        unmount()
        expect(port.close).toHaveBeenCalledTimes(1)
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
        const iframe = screen.getByTitle('Generated widget') as HTMLIFrameElement
        sendNotebookPort(iframe, initialPort)
        fireEvent.load(iframe)
        fireEvent.load(iframe)
        sendNotebookPort(iframe, navigatedPort)

        expect(initialPort.close).toHaveBeenCalledTimes(1)
        expect(navigatedPort.start).not.toHaveBeenCalled()
        expect(onArtifactUnavailable).toHaveBeenCalledTimes(1)
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
        const iframe = screen.getByTitle('Generated widget') as HTMLIFrameElement
        sendNotebookPort(iframe, port)

        act(() => jest.advanceTimersByTime(20_000))
        expect(onArtifactUnavailable).toHaveBeenCalledTimes(1)
    })
})
