/**
 * Whether a trigger config starts on the given internal event. Callers pass whatever trigger a
 * workflow carries, including malformed shapes, so every level is checked before it is read.
 */
export function triggersOnInternalEvent(config: unknown, eventId: string): boolean {
    if (!config || typeof config !== 'object') {
        return false
    }
    const { type, filters } = config as { type?: unknown; filters?: unknown }
    if (type !== 'internal-event' || !filters || typeof filters !== 'object') {
        return false
    }
    const { source, events } = filters as { source?: unknown; events?: unknown }
    return (
        source === 'internal-events' &&
        Array.isArray(events) &&
        events.some((event) => event && typeof event === 'object' && (event as { id?: unknown }).id === eventId)
    )
}
