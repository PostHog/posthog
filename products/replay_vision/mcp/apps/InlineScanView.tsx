import type { ReactElement } from 'react'

import { DescriptionList } from '@posthog/mcp-ui'
import { Badge, Card, CardContent } from '@posthog/quill'

export interface InlineScanResult {
    session_id: string
    scan_outcome: string
}

export interface InlineScanData {
    started: number
    results: InlineScanResult[]
    scan_id?: string | null
    _posthogUrl?: string
}

const outcomeLabel: Record<string, string> = {
    started: 'Scanning',
    already_running: 'Already scanning',
    already_scanned: 'Already scanned',
    skipped_limit: 'Skipped, too many running',
    skipped_quota: 'Skipped, out of credits',
    skipped_scanner_limit: 'Skipped, scanner limit',
    failed: 'Failed to start',
}

const outcomeVariant: Record<string, 'success' | 'destructive' | 'warning' | 'default'> = {
    started: 'success',
    already_running: 'default',
    already_scanned: 'default',
    skipped_limit: 'warning',
    skipped_quota: 'warning',
    skipped_scanner_limit: 'warning',
    failed: 'destructive',
}

export function InlineScanView({ data }: { data: InlineScanData }): ReactElement {
    const total = data.results.length
    const readable = data.results.some(
        (r) =>
            r.scan_outcome === 'already_scanned' || r.scan_outcome === 'started' || r.scan_outcome === 'already_running'
    )

    return (
        <div className="p-4">
            <div className="flex flex-col gap-3">
                <div className="flex flex-col gap-1">
                    <span className="text-lg font-semibold">
                        {data.started} of {total} recording{total === 1 ? '' : 's'} scanning
                    </span>
                    <span className="text-sm text-muted-foreground">
                        {/* Results arrive per recording, so the answer is read back rather than returned here. */}
                        {readable
                            ? 'Read the results with vision-observations-list once each recording finishes.'
                            : 'Nothing started, so there is nothing to read back.'}
                    </span>
                </div>

                {data.scan_id && (
                    <Card>
                        <CardContent>
                            <DescriptionList items={[{ label: 'Scan id', value: data.scan_id }]} />
                        </CardContent>
                    </Card>
                )}

                <Card>
                    <CardContent>
                        <div className="flex flex-col gap-2">
                            {data.results.map((result) => (
                                <div key={result.session_id} className="flex items-center justify-between gap-2">
                                    <span className="text-sm break-all">{result.session_id}</span>
                                    <Badge variant={outcomeVariant[result.scan_outcome] ?? 'default'}>
                                        {outcomeLabel[result.scan_outcome] ?? result.scan_outcome}
                                    </Badge>
                                </div>
                            ))}
                        </div>
                    </CardContent>
                </Card>
            </div>
        </div>
    )
}
