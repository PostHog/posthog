import { IconChevronDown, IconMagicWand } from '@posthog/icons'
import { useActions, useValues } from 'kea'
import { errorPropertiesLogic } from 'lib/components/Errors/errorPropertiesLogic'
import { ExceptionHeaderProps } from 'lib/components/Errors/StackTraces'
import { ErrorTrackingException } from 'lib/components/Errors/types'
import ViewRecordingTrigger from 'lib/components/ViewRecordingButton/ViewRecordingTrigger'
import { IconPlayCircle } from 'lib/lemon-ui/icons'
import { ButtonGroupPrimitive, ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import {
    DropdownMenu,
    DropdownMenuCheckboxItem,
    DropdownMenuContent,
    DropdownMenuItemIndicator,
    DropdownMenuTrigger,
} from 'lib/ui/DropdownMenu/DropdownMenu'
import { TabsPrimitiveContent, TabsPrimitiveContentProps } from 'lib/ui/TabsPrimitive/TabsPrimitive'
import { useState } from 'react'

import { ErrorTrackingRelationalIssue } from '~/queries/schema/schema-general'

import { ExceptionAttributesPreview } from '../../ExceptionAttributesPreview'
import { exceptionCardLogic } from '../exceptionCardLogic'
import { FixModal } from '../FixModal'
import { StacktraceBaseDisplayProps, StacktraceEmptyDisplay } from '../Stacktrace/StacktraceBase'
import { StacktraceGenericDisplay } from '../Stacktrace/StacktraceGenericDisplay'
import { StacktraceTextDisplay } from '../Stacktrace/StacktraceTextDisplay'

export interface StacktraceTabProps extends Omit<TabsPrimitiveContentProps, 'children'> {
    issue?: ErrorTrackingRelationalIssue
    issueLoading: boolean
    timestamp?: string
}

export function StacktraceTab({
    className,
    issue,
    issueLoading,
    timestamp,
    ...props
}: StacktraceTabProps): JSX.Element {
    const { loading } = useValues(exceptionCardLogic)
    const { exceptionAttributes, exceptionList, sessionId } = useValues(errorPropertiesLogic)
    const showFixButton = hasResolvedStackFrames(exceptionList)
    const [showFixModal, setShowFixModal] = useState(false)
    return (
        <TabsPrimitiveContent {...props}>
            <div className="flex justify-between items-center border-b-1 bg-surface-secondary px-2 py-1">
                <div className="flex items-center gap-1">
                    <ExceptionAttributesPreview attributes={exceptionAttributes} loading={loading} />
                </div>
                <ButtonGroupPrimitive size="sm">
                    <ViewRecordingTrigger sessionId={sessionId} inModal={true} timestamp={timestamp}>
                        {(onClick, _, disabledReason, maybeSpinner) => (
                            <ButtonPrimitive
                                disabled={disabledReason != null}
                                onClick={onClick}
                                className="px-2 h-[1.4rem]"
                                tooltip={disabledReason ? disabledReason : 'View recording'}
                            >
                                <IconPlayCircle />
                                View Recording
                                {maybeSpinner}
                            </ButtonPrimitive>
                        )}
                    </ViewRecordingTrigger>
                    {showFixButton && (
                        <ButtonPrimitive
                            onClick={() => setShowFixModal(true)}
                            className="px-2 h-[1.4rem]"
                            tooltip="Generate AI prompt to fix this error"
                        >
                            <IconMagicWand />
                            Fix
                        </ButtonPrimitive>
                    )}
                    <ShowDropDownMenu>
                        <ButtonPrimitive className="px-2 h-[1.4rem]">
                            Show
                            <IconChevronDown />
                        </ButtonPrimitive>
                    </ShowDropDownMenu>
                </ButtonGroupPrimitive>
            </div>
            <StacktraceIssueDisplay
                className="p-2"
                truncateMessage={false}
                issue={issue ?? undefined}
                issueLoading={issueLoading}
            />
            <FixModal isOpen={showFixModal} onClose={() => setShowFixModal(false)} />
        </TabsPrimitiveContent>
    )
}

function StacktraceIssueDisplay({
    issue,
    issueLoading,
    ...stacktraceDisplayProps
}: {
    issue?: ErrorTrackingRelationalIssue
    issueLoading: boolean
} & Omit<StacktraceBaseDisplayProps, 'renderLoading' | 'renderEmpty'>): JSX.Element {
    const { showAsText } = useValues(exceptionCardLogic)
    const componentProps = {
        ...stacktraceDisplayProps,
        renderLoading: (renderHeader: (props: ExceptionHeaderProps) => JSX.Element) =>
            renderHeader({
                type: issue?.name ?? undefined,
                value: issue?.description ?? undefined,
                loading: issueLoading,
            }),
        renderEmpty: () => <StacktraceEmptyDisplay />,
    }
    return showAsText ? <StacktraceTextDisplay {...componentProps} /> : <StacktraceGenericDisplay {...componentProps} />
}

function ShowDropDownMenu({ children }: { children: React.ReactNode }): JSX.Element {
    const { showAllFrames, showAsText } = useValues(exceptionCardLogic)
    const { setShowAllFrames, setShowAsText } = useActions(exceptionCardLogic)
    return (
        <DropdownMenu>
            <DropdownMenuTrigger asChild>{children}</DropdownMenuTrigger>
            <DropdownMenuContent>
                <DropdownMenuCheckboxItem checked={showAllFrames} onCheckedChange={setShowAllFrames} asChild>
                    <ButtonPrimitive menuItem size="sm">
                        <DropdownMenuItemIndicator intent="checkbox" />
                        All frames
                    </ButtonPrimitive>
                </DropdownMenuCheckboxItem>
                <DropdownMenuCheckboxItem checked={showAsText} onCheckedChange={setShowAsText} asChild>
                    <ButtonPrimitive menuItem size="sm">
                        <DropdownMenuItemIndicator intent="checkbox" />
                        As text
                    </ButtonPrimitive>
                </DropdownMenuCheckboxItem>
            </DropdownMenuContent>
        </DropdownMenu>
    )
}

// Helper function to check if any exception has resolved stack frames
function hasResolvedStackFrames(exceptionList: ErrorTrackingException[]): boolean {
    return exceptionList.some((exception) => {
        if (exception.stacktrace?.type === 'resolved' && exception.stacktrace?.frames) {
            return exception.stacktrace.frames.some((frame) => frame.resolved)
        }
        return false
    })
}
