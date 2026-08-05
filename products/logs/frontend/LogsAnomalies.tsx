import { EmptyMessage } from 'lib/components/EmptyMessage/EmptyMessage'

// Intentionally bare: the learning-status surface lands here in a later change.
export function LogsAnomalies(): JSX.Element {
    return (
        <EmptyMessage
            title="Anomaly detection"
            description="PostHog learns each service's normal log volume and surfaces spikes, drops, and silences here, so there's nothing to configure."
        />
    )
}
