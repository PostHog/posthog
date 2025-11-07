import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconChevronDown, IconMagicWand } from '@posthog/icons'

import { ExceptionHeaderProps } from 'lib/components/Errors/StackTraces'
import { errorPropertiesLogic } from 'lib/components/Errors/errorPropertiesLogic'
import { ErrorTrackingException } from 'lib/components/Errors/types'
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

import { ExceptionAttributesPreview } from '../../ExceptionAttributesPreview'
import { ReleasePreviewPill } from '../../ExceptionAttributesPreview/ReleasesPreview/ReleasePreviewPill'
import { useErrorTrackingExplainIssueMaxTool } from '../../ExplainIssueTool'
import { FixModal } from '../FixModal'
import { StacktraceBaseDisplayProps, StacktraceEmptyDisplay } from '../Stacktrace/StacktraceBase'
import { StacktraceGenericDisplay } from '../Stacktrace/StacktraceGenericDisplay'
import { StacktraceTextDisplay } from '../Stacktrace/StacktraceTextDisplay'
import { exceptionCardLogic } from '../exceptionCardLogic'
import { SubHeader } from './SubHeader'

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
    const { exceptionAttributes, exceptionList } = useValues(errorPropertiesLogic)
    const showFixButton = hasResolvedStackFrames(exceptionList)
    const [showFixModal, setShowFixModal] = useState(false)
    const { openMax } = useErrorTrackingExplainIssueMaxTool()

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
