import { LemonTable, LemonTableColumns } from '@posthog/lemon-ui'

import type { MissingSymbolsExampleApi, MissingSymbolsReasonEnumApi } from '../../../generated/api.schemas'

const REASONS: Record<MissingSymbolsReasonEnumApi, string> = {
    chunk_not_uploaded: 'No source map uploaded for this chunk ID',
    no_source_map_linked: 'The script links no source map',
    file_not_reachable: "PostHog couldn't download the script or its source map",
    invalid_source_map: "The source map URL didn't return a source map",
    too_large_to_fetch: 'Too large for PostHog to download, so upload it instead',
    bundle_not_injected: "The bundle has no chunk ID, so the PostHog CLI didn't process it",
    mapping_not_uploaded: 'No mapping file uploaded for this build',
    dsym_not_uploaded: 'No dSYM uploaded for this build',
    debug_symbols_not_uploaded: 'No debug symbols uploaded for this build',
}

const SYMBOL_ID_LABELS: Partial<Record<MissingSymbolsReasonEnumApi, string>> = {
    chunk_not_uploaded: 'Chunk ID',
    mapping_not_uploaded: 'Mapping ID',
    dsym_not_uploaded: 'Debug ID',
    debug_symbols_not_uploaded: 'Debug ID',
}

export function SourceMapsExamplesTable({ examples }: { examples: MissingSymbolsExampleApi[] }): JSX.Element {
    const columns: LemonTableColumns<MissingSymbolsExampleApi> = [
        {
            title: 'Where',
            key: 'location',
            render: (_, example) => (
                <div className="flex flex-col gap-0.5 min-w-0 py-1">
                    <span className="font-mono text-xs break-all">{example.location ?? 'Unknown file'}</span>
                    {example.symbol_id ? (
                        <span className="text-xs text-secondary break-all">
                            {SYMBOL_ID_LABELS[example.reason] ?? 'ID'}: {example.symbol_id}
                        </span>
                    ) : null}
                </div>
            ),
        },
        {
            title: 'Why',
            key: 'reason',
            render: (_, example) => (
                <span className="text-xs">
                    {REASONS[example.reason]}
                    {example.http_status ? ` (HTTP ${example.http_status})` : ''}
                </span>
            ),
        },
        {
            title: 'Frames',
            key: 'frames',
            align: 'right',
            render: (_, example) => example.frames.toLocaleString(),
        },
        {
            title: 'Example function',
            key: 'example_function',
            render: (_, example) => (
                <span className="font-mono text-xs break-all">{example.example_function ?? '-'}</span>
            ),
        },
    ]

    return <LemonTable dataSource={examples} columns={columns} size="small" rowKey={(_, index) => index} />
}
