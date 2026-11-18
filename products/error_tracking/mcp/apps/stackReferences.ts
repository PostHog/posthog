import type { ExceptionData } from './StackTraceView'

/**
 * The API replaces a stack trace that it already returned on the page with a reference to the first copy:
 * `{ same_as_event, same_as_exception }`. Replace each reference with the referenced frames. The reference can point
 * to an earlier exception of the same event or to another event on the page. A reference to an event or an
 * exception that is not in `exceptionsByEvent` stays as it is.
 */
export function resolveStackReferences(
    exceptions: ExceptionData[],
    exceptionsByEvent: Map<string, ExceptionData[]>
): ExceptionData[] {
    return exceptions.map((exception) => {
        const eventUuid = exception.stacktrace?.same_as_event
        const index = exception.stacktrace?.same_as_exception
        if (eventUuid === undefined || index === undefined) {
            return exception
        }
        const source = exceptionsByEvent.get(eventUuid)?.[index]?.stacktrace
        return source?.frames?.length ? { ...exception, stacktrace: source } : exception
    })
}
