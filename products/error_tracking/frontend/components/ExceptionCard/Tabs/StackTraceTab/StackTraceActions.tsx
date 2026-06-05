import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'

import { IconChevronDown, IconInfo, IconMagicWand, IconWrench } from '@posthog/icons'

import { AgentPromptButton } from 'lib/components/AgentPromptButton'
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

import { useStacktraceDisplay } from '../../../../hooks/use-stacktrace-display'
import { useErrorTrackingExplainIssue } from '../../../ExplainIssueTool'
import { buildExplainPrompt, buildFixPrompt } from '../../aiPrompts'
import { exceptionCardLogic } from '../../exceptionCardLogic'

export interface StackTraceActionsProps {
    issue: ErrorTrackingRelationalIssue
}

export function StackTraceActions({ issue }: StackTraceActionsProps): JSX.Element {
    const { exceptionList } = useValues(errorPropertiesLogic)
    const showFixButton = hasResolvedStackFrames(exceptionList)
    const { stacktraceText } = useStacktraceDisplay()
    const { openMax } = useErrorTrackingExplainIssue(issue.id)

    return (
        <div className="flex items-center gap-1">
            {showFixButton && (
                <AgentPromptButton
                    storageKey="error-tracking-issue"
                    data-attr="error-tracking-fix-with-ai"
                    actions={[
                        {
                            key: 'fix',
                            label: 'Fix',
                            icon: <IconWrench />,
                            buildPrompt: () => buildFixPrompt(stacktraceText, issue.id),
                        },
                        {
                            key: 'explain',
                            label: 'Explain',
                            icon: <IconInfo />,
                            buildPrompt: () => buildExplainPrompt(stacktraceText, issue.id),
                        },
                    ]}
                    onRun={({ actionKey, agentKey }) =>
                        posthog.capture('error_tracking_prompt_used', {
                            issue_id: issue.id,
                            mode: actionKey,
                            agent: agentKey,
                        })
                    }
                />
            )}
            <ButtonGroupPrimitive size="sm">
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
            </ButtonGroupPrimitive>
        </div>
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
