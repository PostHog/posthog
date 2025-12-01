import { useActions, useValues } from 'kea'
import { P, match } from 'ts-pattern'

import { CollapsibleExceptionList } from 'lib/components/Errors/ExceptionList/CollapsibleExceptionList'
import { LoadingExceptionList } from 'lib/components/Errors/ExceptionList/LoadingExceptionList'
import { RawExceptionList } from 'lib/components/Errors/ExceptionList/RawExceptionList'
import { errorPropertiesLogic } from 'lib/components/Errors/errorPropertiesLogic'
import posthog from 'lib/posthog-typed'
import { TabsPrimitiveContent, TabsPrimitiveContentProps } from 'lib/ui/TabsPrimitive/TabsPrimitive'

import { ExceptionAttributesPreview } from '../../../ExceptionAttributesPreview'
import { ReleasePreviewPill } from '../../../ExceptionAttributesPreview/ReleasesPreview/ReleasePreviewPill'
import { exceptionCardLogic } from '../../exceptionCardLogic'
import { SubHeader } from './../SubHeader'

export interface StackTraceTabProps extends Omit<TabsPrimitiveContentProps, 'children'> {
    onExplain?: () => void

    renderActions?: () => JSX.Element | null
}

export function StackTraceTab({ className, renderActions, ...props }: StackTraceTabProps): JSX.Element {
    const { loading } = useValues(exceptionCardLogic)
    const { exceptionAttributes } = useValues(errorPropertiesLogic)

    return (
        <TabsPrimitiveContent {...props}>
            <SubHeader className="justify-between">
                <div className="flex items-center gap-1">
                    <ExceptionAttributesPreview attributes={exceptionAttributes} loading={loading} />
                    <ReleasePreviewPill />
                </div>
                {renderActions?.()}
            </SubHeader>
            <StacktraceIssueDisplay className="p-2" />
        </TabsPrimitiveContent>
    )
}

function StacktraceIssueDisplay({ className }: { className?: string }): JSX.Element | null {
    const { showAsText, loading, showAllFrames, issueId } = useValues(exceptionCardLogic)
    const { setShowAllFrames } = useActions(exceptionCardLogic)
    const commonProps = { showAllFrames, setShowAllFrames, className }
    return match([loading, showAsText])
        .with([true, P.any], () => <LoadingExceptionList {...commonProps} />)
        .with([false, true], () => <RawExceptionList {...commonProps} />)
        .with([false, false], () => (
            <CollapsibleExceptionList
                {...commonProps}
                onFirstFrameExpanded={() => {
                    posthog.capture('error_tracking_stacktrace_explored', { issue_id: issueId })
                }}
            />
        ))
        .otherwise(() => null)
}
