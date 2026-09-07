import { identifierToHuman } from 'lib/utils/strings'

// Cymbal stores a symbol set failure as a JSON-serialized `FrameError` (see
// `rust/cymbal/src/core/error.rs`), because it reads the value back to avoid refetching a symbol
// set that already failed. The messages below mirror the `thiserror` messages on that enum, so
// keep the two in step when a variant is added or renamed.

function scalar(payload: unknown): string {
    return typeof payload === 'string' || typeof payload === 'number' ? String(payload) : 'unknown'
}

function hex(payload: unknown): string {
    return typeof payload === 'number' ? `0x${payload.toString(16)}` : scalar(payload)
}

function at(payload: unknown, index: number): string {
    return Array.isArray(payload) ? scalar(payload[index]) : 'unknown'
}

const INVALID_UPLOAD = 'PostHog could not read the uploaded file. Upload it again with the latest PostHog CLI.'

const MESSAGES: Record<string, (payload: unknown) => string> = {
    MissingChunkIdData: (p) => `No symbol set was uploaded for chunk ID ${scalar(p)}.`,

    'JavaScript.NoUrlOrChunkId': () =>
        'This stack frame had no source URL and no chunk ID, so there was nothing to look up.',
    'JavaScript.NoSourceUrl': () => 'This stack frame had no source URL, so there was nothing to look up.',
    'JavaScript.NoSourcemap': (p) =>
        `PostHog found no source map for ${scalar(p)}. Upload one, or check that your build writes a sourceMappingURL comment.`,
    'JavaScript.NoSourcemapUploaded': (p) => `No source map was uploaded for chunk ID ${scalar(p)}.`,
    'JavaScript.InvalidSourceMap': (p) => `PostHog could not parse the source map: ${scalar(p)}.`,
    'JavaScript.InvalidSourceAndMap': () => 'PostHog could not parse the uploaded source and source map.',
    'JavaScript.TokenNotFound': (p) =>
        `The source map has no entry for ${at(p, 0)} line ${at(p, 1)}, column ${at(p, 2)}.`,
    'JavaScript.InvalidSourceUrl': (p) => `The source URL of this stack frame is not a valid URL: ${scalar(p)}.`,
    'JavaScript.InvalidSourceMapHeader': (p) => `The SourceMap header returned by ${scalar(p)} is not readable text.`,
    'JavaScript.InvalidSourceMapUrl': (p) => `The source map URL found at ${scalar(p)} is not a valid URL.`,
    'JavaScript.InvalidDataUrl': (p) => `The data URL at ${at(p, 0)} is not valid: ${at(p, 1)}.`,
    'JavaScript.Timeout': (p) => `The request for ${scalar(p)} timed out.`,
    'JavaScript.HttpStatus': (p) => `Fetching ${at(p, 1)} returned HTTP ${at(p, 0)}.`,
    'JavaScript.NetworkError': (p) => `PostHog could not connect to ${scalar(p)}.`,
    'JavaScript.RedirectError': (p) => `PostHog followed too many redirects while fetching ${scalar(p)}.`,
    'JavaScript.BlockedUrl': (p) => `PostHog does not fetch from private addresses, so ${scalar(p)} was skipped.`,
    'JavaScript.JSDataError': () => INVALID_UPLOAD,

    'Hermes.NoChunkId': () => 'This stack frame had no chunk ID, so there was nothing to look up.',
    'Hermes.NoSourcemapUploaded': (p) => `No source map was uploaded for chunk ID ${scalar(p)}.`,
    'Hermes.InvalidMap': (p) => `PostHog could not parse the Hermes source map: ${scalar(p)}.`,
    'Hermes.NoTokenForColumn': (p) => `The source map for chunk ID ${at(p, 1)} has no entry for column ${at(p, 0)}.`,
    'Hermes.DataError': () => INVALID_UPLOAD,

    'Proguard.NoMapId': () => 'This stack frame had no mapping ID, so there was nothing to look up.',
    'Proguard.NoModuleProvided': () => 'This stack frame had no module name, so there was nothing to look up.',
    'Proguard.MissingMap': (p) => `No ProGuard mapping was uploaded for ID ${scalar(p)}.`,
    'Proguard.InvalidMapping': () => 'PostHog could not parse the uploaded ProGuard mapping.',
    'Proguard.MissingClass': () => 'The ProGuard mapping has no entry for the class in this stack frame.',
    'Proguard.InvalidClass': () => 'The class name of this stack frame is not in a format PostHog can read.',
    'Proguard.NoOriginalFrames': () => 'The ProGuard mapping produced no original stack frames for this frame.',
    'Proguard.DataError': () => INVALID_UPLOAD,

    'Apple.NoDebugId': () => 'This stack frame had no debug ID, so there was nothing to look up.',
    'Apple.MissingDsym': (p) => `No dSYM was uploaded for debug ID ${scalar(p)}.`,
    'Apple.NoMatchingDebugImage': () => 'None of the uploaded debug images match this stack frame.',
    'Apple.InvalidAddress': (p) => `The address of this stack frame is not in a format PostHog can read: ${scalar(p)}.`,
    'Apple.SymbolNotFound': (p) => `The uploaded dSYM has no symbol at address ${hex(p)}.`,
    'Apple.ParseError': (p) => `PostHog could not parse the uploaded dSYM: ${scalar(p)}.`,
    'Apple.DataError': () => INVALID_UPLOAD,

    'Native.NoDebugId': () => 'This stack frame had no debug ID, so there was nothing to look up.',
    'Native.MissingSymbolSet': (p) => `No debug symbols were uploaded for debug ID ${scalar(p)}.`,
    'Native.NoMatchingDebugImage': () => 'None of the uploaded debug images match this stack frame.',
    'Native.InvalidAddress': (p) =>
        `The address of this stack frame is not in a format PostHog can read: ${scalar(p)}.`,
    'Native.SymbolNotFound': (p) => `The uploaded debug symbols have no symbol at address ${hex(p)}.`,
    'Native.ParseError': (p) => `PostHog could not parse the uploaded debug symbols: ${scalar(p)}.`,
    'Native.DataError': () => INVALID_UPLOAD,
}

// Serde writes a unit variant as a bare string and every other variant as a single-key object,
// so both shapes unwrap to a variant name and its payload.
function unwrapVariant(value: unknown): [string, unknown] | null {
    if (typeof value === 'string') {
        return [value, undefined]
    }
    if (value && typeof value === 'object' && !Array.isArray(value)) {
        const keys = Object.keys(value)
        if (keys.length === 1) {
            return [keys[0], (value as Record<string, unknown>)[keys[0]]]
        }
    }
    return null
}

// Keeps an unrecognized variant readable instead of falling back to the raw JSON. The Rust enum
// gains variants independently of this file, so new ones land here until the map catches up.
function describeUnknownVariant(variant: string, payload: unknown): string {
    const sentence = identifierToHuman(variant)
    if (typeof payload === 'string' || typeof payload === 'number') {
        return `${sentence}: ${payload}.`
    }
    return `${sentence}.`
}

export function symbolSetFailureMessage(failureReason: string | null | undefined): string | null {
    if (!failureReason) {
        return null
    }

    let parsed: unknown
    try {
        parsed = JSON.parse(failureReason)
    } catch {
        // Not every stored reason is a serialized `FrameError`, so leave plain text as it is.
        return failureReason
    }

    const outer = unwrapVariant(parsed)
    if (!outer) {
        return failureReason
    }

    const [language, languagePayload] = outer
    const topLevelMessage = MESSAGES[language]
    if (topLevelMessage) {
        return topLevelMessage(languagePayload)
    }

    const inner = unwrapVariant(languagePayload)
    if (!inner) {
        return describeUnknownVariant(language, languagePayload)
    }

    const [variant, payload] = inner
    const message = MESSAGES[`${language}.${variant}`]
    return message ? message(payload) : describeUnknownVariant(variant, payload)
}
