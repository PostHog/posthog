import { IconChevronDown } from '@posthog/icons'
import { useActions, useValues } from 'kea'
import { errorPropertiesLogic } from 'lib/components/Errors/errorPropertiesLogic'
import { ExceptionHeaderProps } from 'lib/components/Errors/StackTraces'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import {
    DropdownMenu,
    DropdownMenuCheckboxItem,
    DropdownMenuContent,
    DropdownMenuItemIndicator,
    DropdownMenuTrigger,
} from 'lib/ui/DropdownMenu/DropdownMenu'
import { TabsContent, TabsContentProps, TabsSubHeader } from 'lib/ui/Tabs'

import { ErrorTrackingRelationalIssue } from '~/queries/schema/schema-general'

import { ExceptionAttributesPreview } from '../../ExceptionAttributesPreview'
import { exceptionCardLogic } from '../exceptionCardLogic'
import { StacktraceBaseDisplayProps, StacktraceEmptyDisplay } from '../Stacktrace/StacktraceBase'
import { StacktraceGenericDisplay } from '../Stacktrace/StacktraceGenericDisplay'
import { StacktraceTextDisplay } from '../Stacktrace/StacktraceTextDisplay'

export interface StacktraceTabProps extends Omit<TabsContentProps, 'children'> {
    issue?: ErrorTrackingRelationalIssue
    issueLoading: boolean
}

export function StacktraceTab({ className, issue, issueLoading, ...props }: StacktraceTabProps): JSX.Element {
    const { loading } = useValues(exceptionCardLogic)
    const { exceptionAttributes } = useValues(errorPropertiesLogic)
    return (
        <TabsContent {...props}>
            <TabsSubHeader className="flex justify-between items-center px-2 py-1">
                <div className="flex items-center gap-1">
                    <ExceptionAttributesPreview attributes={exceptionAttributes} loading={loading} />
                </div>
                <ShowDropDownMenu />
            </TabsSubHeader>
            <StacktraceIssueDisplay
                className="p-2"
                truncateMessage={false}
                issue={issue ?? undefined}
                issueLoading={issueLoading}
            />
        </TabsContent>
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

function ShowDropDownMenu(): JSX.Element {
    const { showAllFrames, showAsText } = useValues(exceptionCardLogic)
    const { setShowAllFrames, setShowAsText } = useActions(exceptionCardLogic)
    return (
        <DropdownMenu>
            <DropdownMenuTrigger asChild>
                <ButtonPrimitive size="sm" className="h-[1.3rem]">
                    Show
                    <IconChevronDown />
                </ButtonPrimitive>
            </DropdownMenuTrigger>
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
