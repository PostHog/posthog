import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconChevronDown, IconMagicWand } from '@posthog/icons'

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

import { ErrorTrackingRelationalIssue } from '~/queries/schema/schema-general'

import { useErrorTrackingExplainIssue } from '../../../ExplainIssueTool'
import { FixModal } from '../../FixModal'
import { exceptionCardLogic } from '../../exceptionCardLogic'

export interface StackTraceActionsProps {
    issue: ErrorTrackingRelationalIssue
}

export function StackTraceActions({ issue }: StackTraceActionsProps): JSX.Element {
    const { exceptionList } = useValues(errorPropertiesLogic)
    const showFixButton = hasResolvedStackFrames(exceptionList)
    const [showFixModal, setShowFixModal] = useState(false)
    const { openMax } = useErrorTrackingExplainIssue()

    return (
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
            <ButtonPrimitive
                onClick={() => openMax()}
                className="px-2 h-[1.4rem]"
                tooltip="Ask PostHog AI for an explanation of this issue"
            >
                <IconMagicWand />
                Explain
            </ButtonPrimitive>
            <ShowDropDownMenu>
                <ButtonPrimitive className="px-2 h-[1.4rem]">
                    Show
                    <IconChevronDown />
                </ButtonPrimitive>
            </ShowDropDownMenu>
            <FixModal isOpen={showFixModal} onClose={() => setShowFixModal(false)} issueId={issue.id} />
        </ButtonGroupPrimitive>
    )
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
