import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'
import { P, match } from 'ts-pattern'

import { IconChevronDown, IconMagicWand } from '@posthog/icons'

import { CollapsibleExceptionList } from 'lib/components/Errors/ExceptionList/CollapsibleExceptionList'
import { LoadingExceptionList } from 'lib/components/Errors/ExceptionList/LoadingExceptionList'
import { RawExceptionList } from 'lib/components/Errors/ExceptionList/RawExceptionList'
import { errorPropertiesLogic } from 'lib/components/Errors/errorPropertiesLogic'
import { ErrorTrackingException } from 'lib/components/Errors/types'
import posthog from 'lib/posthog-typed'
import { ButtonGroupPrimitive, ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import {
    DropdownMenu,
    DropdownMenuCheckboxItem,
    DropdownMenuContent,
    DropdownMenuGroup,
    DropdownMenuItemIndicator,
    DropdownMenuTrigger,
} from 'lib/ui/DropdownMenu/DropdownMenu'
import { TabsPrimitiveContent, TabsPrimitiveContentProps } from 'lib/ui/TabsPrimitive/TabsPrimitive'

import { ErrorTrackingRelationalIssue } from '~/queries/schema/schema-general'

import { ExceptionAttributesPreview } from '../../../ExceptionAttributesPreview'
import { ReleasePreviewPill } from '../../../ExceptionAttributesPreview/ReleasesPreview/ReleasePreviewPill'
import { useErrorTrackingExplainIssueMaxTool } from '../../../ExplainIssueTool'
import { FixModal } from '../../FixModal'
import { exceptionCardLogic } from '../../exceptionCardLogic'
import { SubHeader } from './../SubHeader'

export interface StackTraceTabProps extends Omit<TabsPrimitiveContentProps, 'children'> {
    issue?: ErrorTrackingRelationalIssue
    issueLoading: boolean
    timestamp?: string
}

export function StackTraceTab({
    className,
    issue,
    issueLoading,
    timestamp,
    ...props
}: StackTraceTabProps): JSX.Element {
    const { loading, issueId } = useValues(exceptionCardLogic)
    const { setShowAllFrames } = useActions(exceptionCardLogic)
    const { exceptionAttributes, exceptionList, hasStacktrace, hasInAppFrames, exceptionType } =
        useValues(errorPropertiesLogic)
    const showFixButton = hasResolvedStackFrames(exceptionList)
    const [showFixModal, setShowFixModal] = useState(false)
    const { openMax } = useErrorTrackingExplainIssueMaxTool(issueId, exceptionType)

    useEffect(() => {
        if (!loading) {
            if (hasStacktrace && !hasInAppFrames) {
                setShowAllFrames(true)
            }
        }
    }, [loading, hasStacktrace, hasInAppFrames, setShowAllFrames])

    return (
        <TabsPrimitiveContent {...props}>
            <SubHeader className="justify-between">
                <div className="flex items-center gap-1">
                    <ExceptionAttributesPreview attributes={exceptionAttributes} loading={loading} />
                    <ReleasePreviewPill />
                </div>
                <ButtonGroupPrimitive size="sm">
                    {showFixButton && (
                        <ButtonPrimitive
                            onClick={() => setShowFixModal(true)}
                            className="px-2 h-[1.4rem]"
                            tooltip="Generate AI prompt to fix this error"
                        >
                            <IconMagicWand />
                            Get AI prompt
                        </ButtonPrimitive>
                    )}
                    {openMax && (
                        <ButtonPrimitive
                            onClick={() => openMax()}
                            className="px-2 h-[1.4rem]"
                            tooltip="Ask PostHog AI for an explanation of this issue"
                        >
                            <IconMagicWand />
                            Explain this issue
                        </ButtonPrimitive>
                    )}
                    <ShowDropDownMenu>
                        <ButtonPrimitive className="px-2 h-[1.4rem]">
                            Show
                            <IconChevronDown />
                        </ButtonPrimitive>
                    </ShowDropDownMenu>
                </ButtonGroupPrimitive>
            </SubHeader>
            <StacktraceIssueDisplay className="p-2" issue={issue ?? undefined} issueLoading={issueLoading} />
            <FixModal isOpen={showFixModal} onClose={() => setShowFixModal(false)} issueId={issueId} />
        </TabsPrimitiveContent>
    )
}

function StacktraceIssueDisplay({
    className,
    issue,
    issueLoading,
}: {
    issue?: ErrorTrackingRelationalIssue
    issueLoading: boolean
} & { className?: string }): JSX.Element | null {
    const { showAsText, loading, showAllFrames } = useValues(exceptionCardLogic)
    const { setShowAllFrames } = useActions(exceptionCardLogic)
    const commonProps = { showAllFrames, setShowAllFrames, className }
    return match([issueLoading || loading, showAsText])
        .with([true, P.any], () => <LoadingExceptionList {...commonProps} />)
        .with([false, true], () => <RawExceptionList {...commonProps} />)
        .with([false, false], () => (
            <CollapsibleExceptionList
                {...commonProps}
                onFirstFrameExpanded={() => {
                    posthog.capture('error_tracking_stacktrace_explored', { issue_id: issue?.id })
                }}
            />
        ))
        .otherwise(() => null)
}

function ShowDropDownMenu({ children }: { children: React.ReactNode }): JSX.Element {
    const { showAllFrames, showAsText } = useValues(exceptionCardLogic)
    const { setShowAllFrames, setShowAsText } = useActions(exceptionCardLogic)

    return (
        <DropdownMenu>
            <DropdownMenuTrigger asChild>{children}</DropdownMenuTrigger>
            <DropdownMenuContent>
                <DropdownMenuGroup>
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
                </DropdownMenuGroup>
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
