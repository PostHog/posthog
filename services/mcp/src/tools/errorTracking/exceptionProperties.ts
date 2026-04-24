function asRecord(value: unknown): Record<string, unknown> | undefined {
    return value && typeof value === 'object' && !Array.isArray(value) ? (value as Record<string, unknown>) : undefined
}

function compactObject(record: Record<string, unknown>): Record<string, unknown> {
    return Object.fromEntries(
        Object.entries(record).filter(([, value]) => {
            if (value === undefined || value === null) {
                return false
            }
            if (Array.isArray(value)) {
                return value.length > 0
            }
            if (typeof value === 'object') {
                return Object.keys(value as Record<string, unknown>).length > 0
            }
            return true
        })
    )
}

function parseJsonish(value: unknown): unknown {
    let parsed = value

    for (let i = 0; i < 2; i++) {
        if (typeof parsed !== 'string') {
            return parsed
        }

        const trimmed = parsed.trim()
        if (!trimmed || !['[', '{', '"'].includes(trimmed[0] ?? '')) {
            return parsed
        }

        try {
            parsed = JSON.parse(trimmed)
        } catch {
            return parsed
        }
    }

    return parsed
}

function normalizeFrame(frame: unknown): Record<string, unknown> | undefined {
    const frameRecord = asRecord(parseJsonish(frame))
    if (!frameRecord) {
        return undefined
    }

    return compactObject({
        ...frameRecord,
        mangled_name: frameRecord.mangled_name ?? frameRecord.function ?? frameRecord.name,
        source: frameRecord.source ?? frameRecord.filename ?? frameRecord.abs_path,
        line: frameRecord.line ?? frameRecord.lineno,
        column: frameRecord.column ?? frameRecord.colno,
    })
}

function normalizeStacktrace(stacktrace: unknown): Record<string, unknown> | undefined {
    const stacktraceRecord = asRecord(parseJsonish(stacktrace))
    if (!stacktraceRecord) {
        return undefined
    }

    const frames = Array.isArray(stacktraceRecord.frames)
        ? stacktraceRecord.frames.map(normalizeFrame).filter((frame): frame is Record<string, unknown> => !!frame)
        : undefined

    return compactObject({
        ...stacktraceRecord,
        frames,
    })
}

function normalizeException(exception: unknown): Record<string, unknown> | undefined {
    const exceptionRecord = asRecord(parseJsonish(exception))
    if (!exceptionRecord) {
        return undefined
    }

    return compactObject({
        type: exceptionRecord.type ?? exceptionRecord.exception_type,
        value: exceptionRecord.value ?? exceptionRecord.message ?? exceptionRecord.exception_message,
        module: exceptionRecord.module,
        mechanism: exceptionRecord.mechanism,
        stacktrace: normalizeStacktrace(exceptionRecord.stacktrace),
    })
}

export function normalizeExceptionList(value: unknown): unknown {
    const parsed = parseJsonish(value)
    const record = asRecord(parsed)
    const exceptions = Array.isArray(parsed) ? parsed : Array.isArray(record?.values) ? record.values : undefined

    if (!exceptions) {
        return parsed
    }

    return exceptions.map(normalizeException).filter((exception): exception is Record<string, unknown> => !!exception)
}

export function normalizeErrorTrackingProperty(name: string, value: unknown): unknown {
    if (name === '$exception_list') {
        return normalizeExceptionList(value)
    }
    if (name === '$exception_releases') {
        return parseJsonish(value)
    }
    return value
}
