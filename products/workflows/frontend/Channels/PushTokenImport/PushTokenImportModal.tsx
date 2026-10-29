import { useActions, useValues } from 'kea'

import { IconUpload } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonModal, LemonTable } from '@posthog/lemon-ui'

import { getIntegrationNameFromKind } from 'lib/integrations/utils'
import { LemonFileInput } from 'lib/lemon-ui/LemonFileInput'
import { LemonProgress } from 'lib/lemon-ui/LemonProgress'
import { cn } from 'lib/utils/css-classes'

import { PushTokenFailedRowsTable } from './PushTokenFailedRowsTable'
import { pushTokenImportLogic } from './pushTokenImportLogic'

const PREVIEW_ROWS = 5
const EXAMPLE_CSV = 'distinct_id,device_token\nuser-123,9f2c1a…\nuser-456,dGVzdC1mY20…'

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
        unknownPersonRows,
        startDisabledReason,
    } = useValues(pushTokenImportLogic)
    const { closeImport, setFile, startImport, importUnknownPersons, stopImport } = useActions(pushTokenImportLogic)

    const percent = progress.total ? (progress.rowsDone / progress.total) * 100 : 0

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
            width={720}
            footer={
                importing ? (
                    <LemonButton
                        type="secondary"
                        status="danger"
                        onClick={stopImport}
                        disabledReason={stopping ? 'Stopping the import' : null}
                        data-attr="push-token-import-stop"
                    >
                        Stop import
                    </LemonButton>
                ) : outcome ? (
                    <>
                        {unknownPersonRows.length > 0 ? (
                            <LemonButton
                                type="secondary"
                                onClick={importUnknownPersons}
                                data-attr="push-token-import-create-persons"
                            >
                                Import anyway and create new persons
                            </LemonButton>
                        ) : null}
                        <LemonButton type="primary" onClick={closeImport}>
                            Done
                        </LemonButton>
                    </>
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
            {/* Distinct IDs and device tokens stay out of session recordings. */}
            <div className="flex flex-col gap-4 ph-no-capture ph-replay-block" data-attr="push-token-import-modal">
                {importing ? (
                    <div className="flex flex-col gap-2">
                        <span>
                            <span>{stopping ? 'Stopping the import…' : 'Importing devices…'}</span>{' '}
                            <span translate="no">{progress.rowsDone.toLocaleString()}</span> of{' '}
                            <span translate="no">{progress.total.toLocaleString()}</span> sent.
                        </span>
                        <LemonProgress percent={percent} />
                        <span className="text-xs text-secondary">Keep this page open until the import finishes.</span>
                    </div>
                ) : outcome ? (
                    <>
                        <LemonBanner type={failedRows.length ? 'warning' : 'success'}>
                            {plural(outcome.imported, 'device', 'devices')} imported.
                            {failedRows.length
                                ? ` ${plural(failedRows.length, 'line was', 'lines were')} not imported.`
                                : null}
                        </LemonBanner>
                        {outcome.stoppedReason && outcome.stoppedReason !== 'cancelled' ? (
                            <LemonBanner type="error">The import stopped: {outcome.stoppedReason}</LemonBanner>
                        ) : null}
                        {unknownPersonRows.length > 0 ? (
                            <span className="text-sm">
                                {plural(unknownPersonRows.length, 'device has', 'devices have')} a distinct ID that no
                                person in PostHog has. Check that it's the ID your app passes to identify. If the IDs
                                are right, import them anyway to create those persons.
                            </span>
                        ) : null}
                        {failedRows.length > 0 ? <PushTokenFailedRowsTable rows={failedRows} /> : null}
                    </>
                ) : (
                    <>
                        <span className="text-sm text-secondary">
                            Upload a CSV file of devices, for example an export from your previous push provider. The
                            first line must name the columns, and the file needs a <code>distinct_id</code> column with
                            the ID your app passes to identify, and a <code>device_token</code> column with the APNs
                            device token or FCM registration token. Add one line per device. Other columns are ignored.
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
                                    <>
                                        <span>{plural(parsed.rejected.length, 'line', 'lines')} will be skipped:</span>
                                        <PushTokenFailedRowsTable rows={parsed.rejected} />
                                    </>
                                ) : null}
                            </div>
                        ) : null}
                        <span className="text-xs text-secondary">
                            A distinct ID that no person in PostHog has is not imported, and the result lets you create
                            those persons. Each device is saved with one event, so it counts toward your event usage.
                        </span>
                    </>
                )}
            </div>
        </LemonModal>
    )
}
