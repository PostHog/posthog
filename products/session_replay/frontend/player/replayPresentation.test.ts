import { observeReplayOpenReadiness } from './replayOpenReadiness'
import { canPresentReplayFrame, observeReplayPresentation } from './replayPresentation'

function setBounds(element: Element): void {
    jest.spyOn(element, 'getBoundingClientRect').mockReturnValue({
        x: 0,
        y: 0,
        top: 0,
        left: 0,
        right: 640,
        bottom: 480,
        width: 640,
        height: 480,
        toJSON: () => ({}),
    })
}

describe('replay presentation host', () => {
    afterEach(() => {
        document.body.replaceChildren()
    })

    it.each([false, true])('requires the outer wrapper to be displayed (own document: %s)', async (ownDocument) => {
        const outer = document.createElement('div')
        document.body.appendChild(outer)
        const ownFrame = ownDocument ? document.createElement('iframe') : null
        if (ownFrame) {
            outer.appendChild(ownFrame)
            setBounds(ownFrame)
        }
        const frameDocument = ownFrame?.contentDocument ?? document
        const root = frameDocument.createElement('div')
        ;(ownFrame ? frameDocument.body : outer).appendChild(root)
        const replayFrame = frameDocument.createElement('iframe')
        root.appendChild(replayFrame)
        ;[outer, root, replayFrame].forEach(setBounds)
        const finish = jest.fn()
        const callbacks = new Map<number, FrameRequestCallback>()
        let nextId = 0
        const player = {}
        const readiness = observeReplayOpenReadiness(
            { attemptId: 'synthetic-attempt', firstUseful: jest.fn(), finish, dispose: jest.fn() },
            () => ({ player, canPresent: canPresentReplayFrame(root, replayFrame, outer) }),
            {
                requestFrame: (callback) => {
                    callbacks.set(++nextId, callback)
                    return nextId
                },
                cancelFrame: (id) => callbacks.delete(id),
            }
        )
        const frame = (): void => {
            const pending = [...callbacks.values()]
            callbacks.clear()
            pending.forEach((callback) => callback(0))
        }
        const changed = jest.fn(() => readiness.presentationChanged())
        const dispose = observeReplayPresentation(root, replayFrame, outer, changed)
        expect(canPresentReplayFrame(root, replayFrame, outer)).toBe(true)
        outer.style.display = 'none'
        await Promise.resolve()
        expect(canPresentReplayFrame(root, replayFrame, outer)).toBe(false)
        expect(changed).toHaveBeenCalled()
        readiness.rebuilt(player)
        readiness.positioned(player)
        frame()
        frame()
        expect(finish).not.toHaveBeenCalled()
        expect(callbacks.size).toBe(0)
        changed.mockClear()
        outer.style.display = ''
        await Promise.resolve()
        expect(canPresentReplayFrame(root, replayFrame, outer)).toBe(true)
        expect(changed).toHaveBeenCalledTimes(1)
        frame()
        expect(finish).not.toHaveBeenCalled()
        frame()
        expect(finish).toHaveBeenCalledTimes(1)
        expect(finish).toHaveBeenCalledWith('usable')
        dispose()
        changed.mockClear()
        outer.style.display = 'none'
        await Promise.resolve()
        expect(changed).not.toHaveBeenCalled()
        outer.remove()
        expect(canPresentReplayFrame(root, replayFrame, outer)).toBe(false)
    })
})
