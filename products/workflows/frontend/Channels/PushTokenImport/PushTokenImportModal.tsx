import { useActions, useValues } from 'kea'

import { IconUpload } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonModal, LemonTable } from '@posthog/lemon-ui'

import { downloadBlob } from 'lib/components/ExportButton/exporter'
import { getIntegrationNameFromKind } from 'lib/integrations/utils'
import { LemonFileInput } from 'lib/lemon-ui/LemonFileInput'
import { LemonProgress } from 'lib/lemon-ui/LemonProgress'
import { cn } from 'lib/utils/css-classes'

import { RejectedPushTokenRow, failedRowsCsv } from './pushTokenImport'
import { pushTokenImportLogic } from './pushTokenImportLogic'

const PREVIEW_ROWS = 5
const EXAMPLE_CSV = 'distinct_id,device_token\nuser-123,9f2c1a…\nuser-456,dGVzdC1mY20…'

function countByReason(rows: RejectedPushTokenRow[]): [string, number][] {
    const counts = new Map<string, number>()
    for (const row of rows) {
        counts.set(row.reason, (counts.get(row.reason) ?? 0) + 1)
    }
    return [...counts.entries()]
}

function downloadFailedRows(rows: RejectedPushTokenRow[]): void {
    downloadBlob(new Blob([failedRowsCsv(rows)], { type: 'text/csv' }), 'devices-not-imported.csv')
}

function plural(count: number, one: string, many: string): string {
    return `${count.toLocaleString()} ${count === 1 ? one : many}`
}

/** Registers devices from a CSV export, for example from another push provider, on an APNs or Firebase channel. */
export function PushTokenImportModal(): JSX.Element {
    const {
        isOpen,
        integration,
        file,
        parsed,
        parseError,
        importing,
        stopping,
        progress,
        outcome,
        rowCount,
        failedRows,
        startDisabledReason,
    } = useValues(pushTokenImportLogic)
    const { closeImport, setFile, startImport, stopImport } = useActions(pushTokenImportLogic)

    const percent = rowCount ? (progress.rowsDone / rowCount) * 100 : 0

    return (
        <LemonModal
            isOpen={isOpen}
            onClose={importing ? undefined : closeImport}
            title="Import devices"
            description={
                integration
                    ? `${getIntegrationNameFromKind(integration.kind)} channel: ${integration.display_name}`
                    : undefined
            }
            width={640}
            footer={
                outcome ? (
                    <>
                        {failedRows.length > 0 ? (
                            <LemonButton
                                type="secondary"
                                onClick={() => downloadFailedRows(failedRows)}
                                data-attr="push-token-import-download-failed"
                            >
                                Download rows that failed
                            </LemonButton>
                        ) : null}
                        <LemonButton type="primary" onClick={closeImport}>
                            Done
                        </LemonButton>
                    </>
                ) : importing ? (
                    <LemonButton
                        type="secondary"
                        status="danger"
                        onClick={stopImport}
                        disabledReason={stopping ? 'Stopping after the current batch' : null}
                        data-attr="push-token-import-stop"
                    >
                        Stop import
                    </LemonButton>
                ) : (
                    <>
                        <LemonButton type="secondary" onClick={closeImport}>
                            Cancel
                        </LemonButton>
                        <LemonButton
                            type="primary"
                            onClick={startImport}
                            disabledReason={startDisabledReason}
                            data-attr="push-token-import-start"
                        >
                            {rowCount ? `Import ${plural(rowCount, 'device', 'devices')}` : 'Import'}
                        </LemonButton>
                    </>
                )
            }
        >
            <div className="flex flex-col gap-4" data-attr="push-token-import-modal">
                {outcome ? (
                    <>
                        <LemonBanner type={failedRows.length ? 'warning' : 'success'}>
                            {plural(outcome.imported, 'device', 'devices')} imported.
                            {failedRows.length
                                ? ` ${plural(failedRows.length, 'row was', 'rows were')} not imported. Download them to see why, fix them, and import that file again.`
                                : null}
                        </LemonBanner>
                        {outcome.stoppedReason && outcome.stoppedReason !== 'cancelled' ? (
                            <LemonBanner type="error">The import stopped: {outcome.stoppedReason}</LemonBanner>
                        ) : null}
                    </>
                ) : importing ? (
                    <div className="flex flex-col gap-2">
                        <span>
                            {stopping ? 'Stopping after the current batch…' : 'Importing devices…'}{' '}
                            {progress.rowsDone.toLocaleString()} of {rowCount.toLocaleString()} sent.
                        </span>
                        <LemonProgress percent={percent} />
                        <span className="text-xs text-secondary">Keep this page open until the import finishes.</span>
                    </div>
                ) : (
                    <>
                        <span className="text-sm text-secondary">
                            Upload a CSV file of devices, for example an export from your previous push provider. The
                            first line must name the columns, and the file needs a <code>distinct_id</code> column with
                            the person's ID in your app and a <code>device_token</code> column with the APNs device
                            token or FCM registration token. Add one line per device. Other columns are ignored.
                        </span>
                        <pre className="text-xs bg-surface-secondary rounded p-2 m-0">{EXAMPLE_CSV}</pre>
                        <LemonFileInput
                            accept=".csv,text/csv"
                            multiple={false}
                            value={file ? [file] : []}
                            onChange={(files) => setFile(files[0] ?? null)}
                            showUploadedFiles={false}
                            callToAction={
                                <div
                                    className={cn(
                                        'flex flex-col items-center justify-center flex-1 gap-1 p-8 border border-dashed border-primary hover:border-secondary',
                                        file && 'border-success'
                                    )}
                                >
                                    <IconUpload className="text-5xl text-primary" />
                                    <div>{file ? file.name : 'Drag a CSV file here or click to choose one'}</div>
                                </div>
                            }
                        />
                        {parseError ? <LemonBanner type="error">{parseError}</LemonBanner> : null}
                        {parsed ? (
                            <div className="flex flex-col gap-2" data-attr="push-token-import-preview">
                                <span>
                                    <strong>{plural(parsed.rows.length, 'device', 'devices')}</strong> ready to import.
                                    {parsed.duplicates
                                        ? ` ${plural(parsed.duplicates, 'repeated line was', 'repeated lines were')} left out.`
                                        : null}
                                </span>
                                {parsed.rows.length > 0 ? (
                                    <LemonTable
                                        size="small"
                                        dataSource={parsed.rows.slice(0, PREVIEW_ROWS)}
                                        rowKey="line"
                                        columns={[
                                            { title: 'Line', dataIndex: 'line', width: 0 },
                                            { title: 'Distinct ID', dataIndex: 'distinct_id' },
                                            {
                                                title: 'Device token',
                                                dataIndex: 'device_token',
                                                render: (_, row) => (
                                                    <span className="font-mono text-xs truncate block max-w-80">
                                                        {row.device_token}
                                                    </span>
                                                ),
                                            },
                                        ]}
                                    />
                                ) : null}
                                {parsed.rejected.length > 0 ? (
                                    <LemonBanner
                                        type="warning"
                                        action={{
                                            children: 'Download skipped lines',
                                            onClick: () => downloadFailedRows(parsed.rejected),
                                            'data-attr': 'push-token-import-download-skipped',
                                        }}
                                    >
                                        <div>{plural(parsed.rejected.length, 'line', 'lines')} will be skipped.</div>
                                        <ul className="list-disc pl-4 mt-1">
                                            {countByReason(parsed.rejected).map(([reason, count]) => (
                                                <li key={reason}>
                                                    {reason}: {count.toLocaleString()}
                                                </li>
                                            ))}
                                        </ul>
                                    </LemonBanner>
                                ) : null}
                            </div>
                        ) : null}
                        <span className="text-xs text-secondary">
                            People who aren't in PostHog yet are created. Each device is saved with one event, so it
                            counts toward your event usage.
                        </span>
                    </>
                )}
            </div>
        </LemonModal>
    )
}
