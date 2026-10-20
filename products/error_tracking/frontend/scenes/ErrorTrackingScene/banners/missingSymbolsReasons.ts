import type { MissingSymbolsReasonEnumApi } from '../../../generated/api.schemas'

export const MISSING_SYMBOLS_REASONS: Record<MissingSymbolsReasonEnumApi, { why: string; fix: string }> = {
    chunk_not_uploaded: {
        why: 'No source map uploaded for this chunk ID',
        fix: "Upload this build's source maps with the PostHog CLI.",
    },
    no_source_map_linked: {
        why: 'The script links no source map',
        fix: 'Upload source maps with the PostHog CLI, or serve them next to your scripts.',
    },
    file_not_reachable: {
        why: "PostHog couldn't download the script or its source map",
        fix: 'Upload the source maps with the PostHog CLI, or make the files public so PostHog can download them.',
    },
    invalid_source_map: {
        why: "The source map URL didn't return a source map",
        fix: 'Check that the source map URL returns the map and not an HTML page, or upload the map with the PostHog CLI.',
    },
    too_large_to_fetch: {
        why: 'Too large for PostHog to download',
        fix: 'Upload the source map with the PostHog CLI. Uploads accept larger files than downloads.',
    },
    bundle_not_injected: {
        why: "The bundle has no chunk ID, so the PostHog CLI didn't process it",
        fix: 'Run the PostHog CLI on the bundle to inject chunk IDs, then upload its source map.',
    },
    mapping_not_uploaded: {
        why: 'No mapping file uploaded for this build',
        fix: "Upload this build's mapping file with the PostHog Gradle plugin.",
    },
    dsym_not_uploaded: {
        why: 'No dSYM uploaded for this build',
        fix: "Upload this build's dSYMs with the PostHog CLI.",
    },
    debug_symbols_not_uploaded: {
        why: 'No debug symbols uploaded for this build',
        fix: "Upload this build's debug symbols with the PostHog CLI.",
    },
}

export const SYMBOL_ID_LABELS: Partial<Record<MissingSymbolsReasonEnumApi, string>> = {
    chunk_not_uploaded: 'Chunk ID',
    mapping_not_uploaded: 'Mapping ID',
    dsym_not_uploaded: 'Debug ID',
    debug_symbols_not_uploaded: 'Debug ID',
}
