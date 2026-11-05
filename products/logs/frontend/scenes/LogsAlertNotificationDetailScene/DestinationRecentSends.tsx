import { LemonButton, LemonTable, LemonTag, Tooltip } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'

import { LogsAlertDestinationSendApi } from 'products/logs/frontend/generated/api.schemas'

export interface DestinationRecentSendsProps {
    sends: LogsAlertDestinationSendApi[] | null
    loading: boolean
    error: boolean
    onRetry: () => void
    // Keyed by HogFunction id. A send whose function is gone reads as an unknown event.
    eventLabels: Record<string, string>
}

const PATH_META: Record<LogsAlertDestinationSendApi['path'], { label: string; tooltip: string }> = {
    native: { label: 'PostHog alerts', tooltip: 'Sent by PostHog alerts with the standard message.' },
    hog_function: { label: 'Hog function', tooltip: "Sent by this destination's hog function." },
}

export function DestinationRecentSends({
    sends,
    loading,
    error,
    onRetry,
    eventLabels,
}: DestinationRecentSendsProps): JSX.Element {
    return (
        <div className="flex flex-col gap-2">
            <div>
                <h3 className="text-base font-semibold m-0">Recent sends</h3>
                <p className="text-sm text-muted m-0">Messages sent to this destination in the last 7 days.</p>
            </div>
            {error && !loading ? (
                <div className="flex items-center justify-between gap-2 border rounded p-3">
                    <span className="text-sm">Couldn't load recent sends.</span>
                    <LemonButton
                        size="small"
                        type="secondary"
                        onClick={onRetry}
                        data-attr="logs-alert-destination-sends-retry"
                    >
                        Retry
                    </LemonButton>
                </div>
            ) : (
                <LemonTable
                    dataSource={sends ?? []}
                    loading={loading || sends === null}
                    rowKey={(send) => `${send.hog_function_id}:${send.path}:${send.sent_at}`}
                    size="small"
                    emptyState="Nothing sent in the last 7 days. Sends show here after the alert fires."
                    columns={[
                        {
                            title: 'Sent',
                            key: 'sent_at',
                            render: (_, send) => <TZLabel time={send.sent_at} />,
                        },
                        {
                            title: 'Event',
                            key: 'event',
                            render: (_, send) => eventLabels[send.hog_function_id] ?? 'Unknown event',
                        },
                        {
                            title: 'Outcome',
                            key: 'outcome',
                            render: (_, send) =>
                                send.succeeded ? (
                                    <LemonTag type="success">Sent</LemonTag>
                                ) : (
                                    <div className="flex flex-col items-start gap-1 min-w-0">
                                        <LemonTag type="danger">Failed</LemonTag>
                                        {send.error ? (
                                            <span className="text-xs text-muted break-words">{send.error}</span>
                                        ) : send.path === 'hog_function' ? (
                                            <span className="text-xs text-muted">
                                                The reason is in this event's hog function logs.
                                            </span>
                                        ) : null}
                                    </div>
                                ),
                        },
                        {
                            title: 'Sent by',
                            key: 'path',
                            render: (_, send) => (
                                <Tooltip title={PATH_META[send.path].tooltip}>
                                    <LemonTag>{PATH_META[send.path].label}</LemonTag>
                                </Tooltip>
                            ),
                        },
                    ]}
                />
            )}
        </div>
    )
}
