import { useActions, useValues } from 'kea'
import { P, match } from 'ts-pattern'

import { errorPropertiesLogic } from 'lib/components/Errors/errorPropertiesLogic'
import { CollapsibleExceptionList } from 'lib/components/Errors/ExceptionList/CollapsibleExceptionList'
import { LoadingExceptionList } from 'lib/components/Errors/ExceptionList/LoadingExceptionList'
import { RawExceptionList } from 'lib/components/Errors/ExceptionList/RawExceptionList'
import { TabsPrimitiveContent, TabsPrimitiveContentProps } from 'lib/ui/TabsPrimitive/TabsPrimitive'
import { cn } from 'lib/utils/css-classes'

import { ExceptionAttributesPreview } from '../../../ExceptionAttributesPreview'
import { ReleasePreviewPill } from '../../../ReleasesPreview/ReleasePreviewPill'
import { exceptionCardLogic } from '../../exceptionCardLogic'
import { SubHeader } from './../SubHeader'

export interface StackTraceTabProps extends Omit<TabsPrimitiveContentProps, 'children'> {
    onExplain?: () => void

    renderActions?: () => JSX.Element | null
}

export function StackTraceTab({ className, renderActions, ...props }: StackTraceTabProps): JSX.Element {
    const { loading } = useValues(exceptionCardLogic)
    const { exceptionAttributes, release } = useValues(errorPropertiesLogic)

    return (
        <TabsPrimitiveContent {...props} className={cn('flex flex-col', className)}>
            <SubHeader className="justify-between shrink-0">
                <div className="flex items-center gap-1">
                    <ExceptionAttributesPreview attributes={exceptionAttributes} loading={loading} />
                    {release && <ReleasePreviewPill release={release} />}
                </div>
                {renderActions?.()}
            </SubHeader>
            <div className="flex-1 min-h-0 overflow-y-auto">
                <StacktraceIssueDisplay className="p-2" />
            </div>
        </TabsPrimitiveContent>
    )
}

function StacktraceIssueDisplay({ className }: { className?: string }): JSX.Element | null {
    const { showAsText, loading, showAllFrames, expandedFrameRawIds } = useValues(exceptionCardLogic)
    const { setShowAllFrames, setFrameExpanded } = useActions(exceptionCardLogic)
    const commonProps = { showAllFrames, setShowAllFrames, className }

    return match([loading, showAsText])
        .with([true, P.any], () => <LoadingExceptionList {...commonProps} />)
        .with([false, true], () => <RawExceptionList {...commonProps} />)
        .with([false, false], () => (
            <CollapsibleExceptionList
                {...commonProps}
                expandedFrameRawIds={expandedFrameRawIds}
                onFrameExpandedChange={setFrameExpanded}
            />
        ))
        .otherwise(() => null)
}
