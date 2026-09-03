import { objectsEqual } from 'lib/utils/objects'

import type { ObservationVersionMarkerApi } from '../../generated/api.schemas'
import { ReplayScanner, SAMPLING_MODE_OPTIONS, ScannerType, modelLabel, scannerTypeLabel } from '../types'
import { fieldEditor, formatChangeValue } from './configChanges'

/** One version's full version-tracked config, from a run snapshot or from the live scanner.
 * A null top-level field means the run snapshots didn't record it, which is not the same as unset. */
export interface VersionConfig {
    version: number
    scannerType?: string | null
    model?: string | null
    provider?: string | null
    emitsSignals?: boolean | null
    samplingRate?: number | null
    samplingMode?: string | null
    query?: unknown
    scannerConfig: Record<string, unknown>
}

export interface VersionFieldChange {
    field: string
    label: string
    /** `value` reads as "before → after". A prompt or filter change is too big for one line. */
    kind: 'prompt' | 'query' | 'value'
    before: string
    after: string
}

export interface VersionChanges {
    /** The version this one is compared against. */
    previous: VersionConfig
    changes: VersionFieldChange[]
    /** Version-tracked fields one of the two versions didn't record, so they couldn't be compared. */
    notRecorded: string[]
}

/** Labels match the configuration tab's own, so both surfaces read the same. */
const SCANNER_FIELDS: { field: keyof VersionConfig; label: string; format: (value: unknown) => string }[] = [
    { field: 'scannerType', label: 'Type', format: (v) => scannerTypeLabel(v as ScannerType) },
    { field: 'model', label: 'Model', format: (v) => modelLabel(v as string) },
    { field: 'provider', label: 'Provider', format: (v) => String(v) },
    { field: 'emitsSignals', label: 'Emit signals', format: formatChangeValue },
    { field: 'samplingMode', label: 'Session coverage', format: (v) => optionLabel(SAMPLING_MODE_OPTIONS, v) },
    { field: 'samplingRate', label: 'Sampling', format: (v) => `${Math.round(Number(v) * 1000) / 10}%` },
]

function optionLabel(options: readonly { value: string; label: string }[], value: unknown): string {
    return options.find((option) => option.value === value)?.label ?? String(value)
}

/** Humanizes one config value for the one-line change readout. */
export function formatConfigValue(field: string, value: unknown): string {
    const { kind } = fieldEditor(field, value)
    if (value === undefined || value === null) {
        // An absent flag is off, not unknown: scanner_config is always snapshotted whole.
        return kind === 'flag' ? 'off' : '—'
    }
    if (kind === 'tags') {
        const tags = value as unknown[]
        return tags.length ? tags.join(', ') : 'none'
    }
    return formatChangeValue(value)
}

/** Every version-tracked field that differs between two versions, for the "what changed" readout.
 * Top-level fields only compare when both versions recorded them. Config keys always compare, since
 * scanner_config is snapshotted whole and an absent key means the value is unset. */
export function diffVersionConfigs(previous: VersionConfig, current: VersionConfig): VersionChanges {
    const changes: VersionFieldChange[] = []
    const notRecorded: string[] = []

    for (const { field, label, format } of SCANNER_FIELDS) {
        const before = previous[field]
        const after = current[field]
        if (before == null || after == null) {
            notRecorded.push(label)
        } else if (before !== after) {
            changes.push({ field, label, kind: 'value', before: format(before), after: format(after) })
        }
    }

    if (previous.query == null || current.query == null) {
        notRecorded.push('Recording filters')
    } else if (!objectsEqual(previous.query, current.query)) {
        changes.push({ field: 'query', label: 'Recording filters', kind: 'query', before: '', after: '' })
    }

    for (const key of new Set([...Object.keys(previous.scannerConfig), ...Object.keys(current.scannerConfig)])) {
        const before = previous.scannerConfig[key]
        const after = current.scannerConfig[key]
        if (objectsEqual(before ?? null, after ?? null)) {
            continue
        }
        const { kind, label } = fieldEditor(key, after ?? before)
        const isPrompt = kind === 'prompt'
        changes.push({
            field: key,
            label,
            kind: isPrompt ? 'prompt' : 'value',
            // The prompt carries its raw text, since a diff, not a one-line summary, is what reads clearly.
            before: isPrompt ? String(before ?? '') : formatConfigValue(key, before),
            after: isPrompt ? String(after ?? '') : formatConfigValue(key, after),
        })
    }

    // Prompt first, since it is the change that matters most.
    changes.sort((a, b) => Number(b.kind === 'prompt') - Number(a.kind === 'prompt'))
    return { previous, changes, notRecorded }
}

/** The live scanner as a version, so a freshly saved version with no scans yet still shows what it changed. */
export function versionConfigFromScanner(scanner: ReplayScanner): VersionConfig {
    return {
        version: scanner.scanner_version,
        scannerType: scanner.scanner_type,
        model: scanner.model,
        provider: scanner.provider,
        emitsSignals: scanner.emits_signals,
        samplingRate: scanner.sampling_rate,
        samplingMode: scanner.sampling_mode,
        query: scanner.query ?? {},
        scannerConfig: scanner.scanner_config as unknown as Record<string, unknown>,
    }
}

export function versionConfigFromMarker(marker: ObservationVersionMarkerApi): VersionConfig {
    return {
        version: marker.version,
        scannerType: marker.scanner_type,
        model: marker.model,
        provider: marker.provider,
        emitsSignals: marker.emits_signals,
        samplingRate: marker.sampling_rate,
        samplingMode: marker.sampling_mode,
        query: marker.query,
        scannerConfig: (marker.scanner_config as Record<string, unknown>) ?? {},
    }
}

/** Version -> what it changed, against the next-oldest version present. Versions that scanned nothing
 * leave gaps, so that isn't always version - 1. The oldest gets no entry. */
export function versionChangesByVersion(versions: VersionConfig[]): Map<number, VersionChanges> {
    const ascending = [...versions].sort((a, b) => a.version - b.version)
    const result = new Map<number, VersionChanges>()
    for (let index = 1; index < ascending.length; index++) {
        result.set(ascending[index].version, diffVersionConfigs(ascending[index - 1], ascending[index]))
    }
    return result
}
