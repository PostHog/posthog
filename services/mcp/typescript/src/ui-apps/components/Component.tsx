import type { ReactElement, CSSProperties } from 'react'
import type {
    VisualizationPayload,
    TrendsPayload,
    FunnelPayload,
    TablePayload,
    ErrorListPayload,
    ErrorTracePayload,
} from './types'
import { TrendsVisualizer } from './TrendsVisualizer'
import { FunnelVisualizer } from './FunnelVisualizer'
import { TableVisualizer } from './TableVisualizer'
import { ErrorListVisualizer } from './ErrorListVisualizer'
import { ErrorTraceVisualizer } from './ErrorTraceVisualizer'
import { PostHogLink } from './PostHogLink'

function isVisualizationPayload(data: unknown): data is VisualizationPayload {
    return (
        typeof data === 'object' &&
        data !== null &&
        '_visualization' in data &&
        typeof (data as VisualizationPayload)._visualization === 'string'
    )
}

export interface ComponentProps {
    data: unknown
    onOpenLink?: (url: string) => void
}

export function Component({ data, onOpenLink }: ComponentProps): ReactElement {
    const containerStyle: CSSProperties = {
        fontFamily: 'var(--font-sans, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif)',
        color: 'var(--color-text-primary, #101828)',
        backgroundColor: 'var(--color-background-primary, #fff)',
        padding: '1rem',
        borderRadius: 'var(--border-radius-lg, 0.5rem)',
        border: '1px solid var(--color-border-primary, #e5e7eb)',
    }

    const titleStyle: CSSProperties = {
        fontSize: '0.875rem',
        fontWeight: 600,
        color: 'var(--color-text-secondary, #6b7280)',
        marginBottom: '1rem',
        textTransform: 'uppercase',
        letterSpacing: '0.05em',
    }

    if (!isVisualizationPayload(data)) {
        return (
            <div style={containerStyle}>
                <div
                    style={{
                        padding: '2rem',
                        textAlign: 'center',
                        color: 'var(--color-text-secondary, #6b7280)',
                    }}
                >
                    Invalid data format. Expected _visualization field.
                </div>
            </div>
        )
    }

    const payload = data

    const renderVisualization = (): ReactElement => {
        switch (payload._visualization) {
            case 'trends':
                return (
                    <TrendsVisualizer
                        query={(payload as TrendsPayload).query}
                        results={(payload as TrendsPayload).results}
                    />
                )

            case 'funnel':
                return (
                    <FunnelVisualizer
                        query={(payload as FunnelPayload).query}
                        results={(payload as FunnelPayload).results}
                    />
                )

            case 'table':
                return <TableVisualizer results={(payload as TablePayload).results} />

            case 'error-list':
                return <ErrorListVisualizer issues={(payload as ErrorListPayload).issues} />

            case 'error-trace':
                return (
                    <ErrorTraceVisualizer
                        issue={(payload as ErrorTracePayload).issue}
                        traces={(payload as ErrorTracePayload).traces}
                    />
                )

            default:
                return (
                    <div style={{ color: 'var(--color-text-secondary, #6b7280)' }}>
                        Unknown visualization type: {(payload as VisualizationPayload)._visualization}
                    </div>
                )
        }
    }

    const getTitle = (): string => {
        switch (payload._visualization) {
            case 'trends':
                return 'Trends'
            case 'funnel':
                return 'Funnel'
            case 'table':
                return 'Query results'
            case 'error-list':
                return 'Errors'
            case 'error-trace':
                return 'Error trace'
            default:
                return 'Results'
        }
    }

    return (
        <div style={containerStyle}>
            <div style={titleStyle}>{getTitle()}</div>
            {renderVisualization()}
            {payload._posthogUrl && <PostHogLink url={payload._posthogUrl} onOpen={onOpenLink} />}
        </div>
    )
}
