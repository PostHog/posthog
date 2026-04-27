import { asRecord, compactObject } from './utils'

const MAX_NORMALIZED_TEXT_CHARS = 1000
const TRUNCATABLE_PROPERTY_NAMES = new Set(['$exception_message', '$exception_value'])

function truncateText(value: unknown, options: NormalizeOptions): unknown {
    if (options.verbosity === 'raw' || typeof value !== 'string' || value.length <= MAX_NORMALIZED_TEXT_CHARS) {
        return value
    }

    const suffix = `… [truncated from ${value.length} chars]`
    return `${value.slice(0, MAX_NORMALIZED_TEXT_CHARS - suffix.length)}${suffix}`
}

function parseJsonish(value: unknown): unknown {
    // HogQL property access over StringJSONDatabaseField returns arrays/objects as raw JSON strings.
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

export type ExceptionVerbosity = 'summary' | 'stack' | 'raw'

type NormalizeOptions = {
    verbosity?: ExceptionVerbosity
    onlyAppFrames?: boolean
}

function stripNonRawFields(record: Record<string, unknown>): Record<string, unknown> {
    const { junk_drawer: _junkDrawer, raw_id: _rawId, ...rest } = record
    return rest
}

function normalizeFrame(frame: unknown, options: NormalizeOptions): Record<string, unknown> | undefined {
    const frameRecord = asRecord(parseJsonish(frame))
    if (!frameRecord) {
        return undefined
    }
    if (options.onlyAppFrames !== false && frameRecord.in_app !== true) {
        return undefined
    }
    const baseFrame = options.verbosity === 'raw' ? frameRecord : stripNonRawFields(frameRecord)

    return compactObject({
        ...baseFrame,
        mangled_name: frameRecord.mangled_name ?? frameRecord.function ?? frameRecord.name,
        source: frameRecord.source ?? frameRecord.filename ?? frameRecord.abs_path,
        line: frameRecord.line ?? frameRecord.lineno,
        column: frameRecord.column ?? frameRecord.colno,
    })
}

function normalizeStacktrace(stacktrace: unknown, options: NormalizeOptions): Record<string, unknown> | undefined {
    const stacktraceRecord = asRecord(parseJsonish(stacktrace))
    if (!stacktraceRecord) {
        return undefined
    }

    const frames = Array.isArray(stacktraceRecord.frames)
        ? stacktraceRecord.frames
              .map((frame) => normalizeFrame(frame, options))
              .filter((frame): frame is Record<string, unknown> => !!frame)
        : undefined
    const baseStacktrace = options.verbosity === 'raw' ? stacktraceRecord : stripNonRawFields(stacktraceRecord)

    return compactObject({
        ...baseStacktrace,
        frames,
    })
}

function normalizeException(exception: unknown, options: NormalizeOptions): Record<string, unknown> | undefined {
    const exceptionRecord = asRecord(parseJsonish(exception))
    if (!exceptionRecord) {
        return undefined
    }

    const summary = compactObject({
        type: exceptionRecord.type ?? exceptionRecord.exception_type,
        value: truncateText(
            exceptionRecord.value ?? exceptionRecord.message ?? exceptionRecord.exception_message,
            options
        ),
        module: exceptionRecord.module,
        mechanism: exceptionRecord.mechanism,
    })

    if (options.verbosity === 'summary') {
        return summary
    }

    const stacktrace = normalizeStacktrace(exceptionRecord.stacktrace, options)
    if (options.verbosity === 'raw') {
        return compactObject({
            ...exceptionRecord,
            stacktrace,
        })
    }

    return compactObject({
        ...summary,
        stacktrace,
    })
}

export function normalizeExceptionList(value: unknown, options: NormalizeOptions = {}): unknown {
    const parsed = parseJsonish(value)
    const record = asRecord(parsed)
    const exceptions = Array.isArray(parsed) ? parsed : Array.isArray(record?.values) ? record.values : undefined
    const normalizeOptions = {
        verbosity: options.verbosity ?? 'summary',
        onlyAppFrames: options.onlyAppFrames ?? true,
    }

    if (!exceptions) {
        return parsed
    }

    return exceptions
        .map((exception) => normalizeException(exception, normalizeOptions))
        .filter((exception): exception is Record<string, unknown> => !!exception)
}

export function normalizeErrorTrackingProperty(name: string, value: unknown, options: NormalizeOptions = {}): unknown {
    if (name === '$exception_list') {
        return normalizeExceptionList(value, options)
    }
    if (name === '$exception_releases') {
        return parseJsonish(value)
    }
    if (TRUNCATABLE_PROPERTY_NAMES.has(name)) {
        return truncateText(value, options)
    }
    return value
}
