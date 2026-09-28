import { type ExceptionData, resolveStackReferences } from './StackTraceView'

jest.mock('@posthog/quill', () => ({}), { virtual: true })

describe('resolveStackReferences', () => {
    it('shows the frames of the earlier exception that a reference points to', () => {
        const frames = [{ mangled_name: 'submitOrder', in_app: true }]
        const exceptions: ExceptionData[] = [
            { type: 'TypeError', value: 'first', stacktrace: { frames } },
            { type: 'Error', value: 'second', stacktrace: { same_as_event: 'event-1', same_as_exception: 0 } },
        ]

        const resolved = resolveStackReferences(exceptions)

        expect(resolved[1].stacktrace?.frames).toEqual(frames)
        expect(resolved[1].value).toBe('second')
    })

    it('keeps a reference that points to no frames', () => {
        const exceptions: ExceptionData[] = [
            { type: 'Error', value: 'only', stacktrace: { same_as_event: 'event-1', same_as_exception: 3 } },
        ]

        expect(resolveStackReferences(exceptions)).toEqual(exceptions)
    })
})
