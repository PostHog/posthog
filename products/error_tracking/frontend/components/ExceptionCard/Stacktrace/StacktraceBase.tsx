import { EmptyMessage } from 'lib/components/EmptyMessage/EmptyMessage'
import { ExceptionHeaderProps } from 'lib/components/Errors/StackTraces'
import { ErrorTrackingRuntime, FingerprintRecordPart } from 'lib/components/Errors/types'

export type HeaderRenderer = (props: ExceptionHeaderProps) => JSX.Element
export interface StacktraceBaseDisplayProps {
    className?: string
    truncateMessage: boolean
    renderLoading: (renderHeader: HeaderRenderer) => JSX.Element
    renderEmpty: () => JSX.Element
}

export interface StacktraceBaseExceptionHeaderProps {
    type?: string
    value?: string
    loading: boolean
    runtime?: ErrorTrackingRuntime
    part?: FingerprintRecordPart
    truncate: boolean
}

export function StacktraceEmptyDisplay(): JSX.Element {
    return (
        <EmptyMessage
            title="No stacktrace available"
            description="Make sure the SDK is set up correctly or contact support if problem persists"
            buttonText="Check documentation"
            buttonTo="https://posthog.com/docs/error-tracking/installation"
            size="small"
        />
    )
}
