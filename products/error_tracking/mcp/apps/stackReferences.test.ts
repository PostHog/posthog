import { resolveStackReferences } from './stackReferences'
import type { ExceptionData } from './StackTraceView'

const checkoutFrames = [{ mangled_name: 'submitOrder', in_app: true }]
const cartFrames = [{ mangled_name: 'loadCart', in_app: true }]

describe('resolveStackReferences', () => {
    it('resolves a reference to an earlier exception of the same event', () => {
        const exceptions: ExceptionData[] = [
            { type: 'TypeError', value: 'first', stacktrace: { frames: checkoutFrames } },
            { type: 'Error', value: 'second', stacktrace: { same_as_event: 'event-1', same_as_exception: 0 } },
        ]

        const resolved = resolveStackReferences(exceptions, new Map([['event-1', exceptions]]))

        expect(resolved[1].stacktrace?.frames).toEqual(checkoutFrames)
        expect(resolved[1].value).toBe('second')
    })

    it('reads a reference to another event from that event, not from the same index of this event', () => {
        const otherEvent: ExceptionData[] = [{ type: 'TypeError', value: 'other', stacktrace: { frames: cartFrames } }]
        const exceptions: ExceptionData[] = [
            { type: 'TypeError', value: 'own', stacktrace: { frames: checkoutFrames } },
            { type: 'Error', value: 'repeated', stacktrace: { same_as_event: 'event-0', same_as_exception: 0 } },
        ]
        const exceptionsByEvent = new Map([
            ['event-0', otherEvent],
            ['event-1', exceptions],
        ])

        expect(resolveStackReferences(exceptions, exceptionsByEvent)[1].stacktrace?.frames).toEqual(cartFrames)
    })

    it('leaves a reference to an event that is not on the page', () => {
        const exceptions: ExceptionData[] = [
            { type: 'TypeError', value: 'own', stacktrace: { frames: checkoutFrames } },
            { type: 'Error', value: 'repeated', stacktrace: { same_as_event: 'event-9', same_as_exception: 0 } },
        ]

        expect(resolveStackReferences(exceptions, new Map([['event-1', exceptions]]))).toEqual(exceptions)
    })
})
