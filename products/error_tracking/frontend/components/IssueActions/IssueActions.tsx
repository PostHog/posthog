import { useActions, useValues } from 'kea'

import { LemonDialog } from '@posthog/lemon-ui'

import { useHogfetti } from 'lib/components/Hogfetti/Hogfetti'
import {
    Button,
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from 'lib/ui/quill'
import { newInternalTab } from 'lib/utils/newInternalTab'
import { urls } from 'scenes/urls'

import { ErrorTrackingIssue } from '~/queries/schema/schema-general'
import { FilterLogicalOperator, HogQLPropertyFilter, PropertyFilterType, UniversalFiltersGroup } from '~/types'

import { bulkSelectLogic } from '../../logics/bulkSelectLogic'
import { AssigneeLabelDisplay } from '../Assignee/AssigneeDisplay'
import { AssigneeSelect } from '../Assignee/AssigneeSelect'
import { IssueStatus, StatusIndicator } from '../Indicators'
import { issueFiltersLogic } from '../IssueFilters/issueFiltersLogic'
import { issueActionsLogic } from './issueActionsLogic'

export interface IssueActionsProps {
    issues: ErrorTrackingIssue[]
    selectedIds: string[]
}

export function IssueActions({ issues, selectedIds }: IssueActionsProps): JSX.Element {
    const { mergeIssues, assignIssues, resolveIssues, suppressIssues, activateIssues } = useActions(issueActionsLogic)
    const { filterGroup } = useValues(issueFiltersLogic)
    const { setFilterGroup } = useActions(issueFiltersLogic)
    const { setSelectedIssueIds } = useActions(bulkSelectLogic)
    const { trigger: triggerHogfetti, HogfettiComponent } = useHogfetti()

    const hasAtLeastTwoIssues = selectedIds.length >= 2

    const openInNewTabs = (): void => {
        selectedIds.forEach((id) => {
            const issue = issues.find((issue) => issue.id === id)
            if (issue) {
                newInternalTab(urls.errorTrackingIssue(id, { timestamp: issue.last_seen }))
            }
        })
    }

    const excludeSelectedIssues = (): void => {
        const quotedIds = selectedIds.map((id) => `'${id}'`).join(', ')
        const newFilter: HogQLPropertyFilter = {
            key: `issue_id NOT IN (${quotedIds})`,
            type: PropertyFilterType.HogQL,
            value: null,
        }

        const firstGroup = filterGroup.values[0] as UniversalFiltersGroup

        const updatedFirstGroup = { ...firstGroup, values: [...firstGroup.values, newFilter] }

        setFilterGroup({
            type: FilterLogicalOperator.And,
            values: [updatedFirstGroup],
        })
        setSelectedIssueIds([])
    }

    const currentStatus = issues
        .filter((issue: ErrorTrackingIssue) => selectedIds.includes(issue.id))
        .map((issue: ErrorTrackingIssue) => issue.status as IssueStatus)
        .reduce<IssueStatus | 'mixed' | null>((acc, status) => {
            if (acc === null) {
                return status
            } else if (acc === 'mixed') {
                return 'mixed'
            } else if (acc !== status) {
                return 'mixed'
            }
            return acc
        }, null)

    let options: IssueStatus[] = ['active', 'resolved', 'suppressed']

    const mergeButton = (
        <Button
            variant="outline"
            disabled={!hasAtLeastTwoIssues}
            onClick={() =>
                LemonDialog.open({
                    title: 'Merge Issues',
                    content: `Are you sure you want to merge these ${selectedIds.length} issues?`,
                    primaryButton: {
                        children: 'Merge',
                        status: 'danger',
                        onClick: () => {
                            mergeIssues(selectedIds)
                        },
                    },
                })
            }
        >
            Merge
        </Button>
    )

    return (
        <div className="flex gap-x-2 justify-between">
            <HogfettiComponent />
            <div className="flex gap-x-2">
                <Button variant="outline" onClick={openInNewTabs}>
                    Open all
                </Button>
                {hasAtLeastTwoIssues ? (
                    mergeButton
                ) : (
                    <Tooltip>
                        <TooltipTrigger render={mergeButton} />
                        <TooltipContent>Select at least two issues to merge</TooltipContent>
                    </Tooltip>
                )}
                <Select
                    value={currentStatus === 'mixed' ? null : currentStatus}
                    onValueChange={(value) => {
                        if (!value || value === currentStatus) {
                            return
                        }
                        switch (value) {
                            case 'resolved':
                                resolveIssues(selectedIds)
                                ;[0, 400, 800].forEach((delay) => setTimeout(triggerHogfetti, delay))
                                break
                            case 'suppressed':
                                suppressIssues(selectedIds)
                                break
                            case 'active':
                                activateIssues(selectedIds)
                                break
                            default:
                                break
                        }
                    }}
                >
                    <SelectTrigger>
                        <SelectValue>
                            {currentStatus && currentStatus !== 'mixed' ? (
                                <StatusIndicator status={currentStatus} size="xsmall" className="w-full" />
                            ) : (
                                'Mark as'
                            )}
                        </SelectValue>
                    </SelectTrigger>
                    <SelectContent align="start" alignItemWithTrigger={false}>
                        {options.map((status) => (
                            <SelectItem key={status} value={status}>
                                <StatusIndicator status={status} size="xsmall" className="w-full" withTooltip="right" />
                            </SelectItem>
                        ))}
                    </SelectContent>
                </Select>
                <AssigneeSelect assignee={null} onChange={(assignee) => assignIssues(selectedIds, assignee)}>
                    {(displayAssignee) => (
                        <Button variant="outline">
                            <AssigneeLabelDisplay assignee={displayAssignee} placeholder="Assign" />
                        </Button>
                    )}
                </AssigneeSelect>
                {issues.some((issue) => selectedIds.includes(issue.id) && issue.assignee != null) && (
                    <Button variant="outline" onClick={() => assignIssues(selectedIds, null)}>
                        Unassign
                    </Button>
                )}
            </div>
            <Button variant="outline" onClick={excludeSelectedIssues}>
                Hide from search
            </Button>
        </div>
    )
}
