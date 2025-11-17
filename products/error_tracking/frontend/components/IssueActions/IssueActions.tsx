import { useActions, useValues } from 'kea'

import { LemonButton, LemonDialog, LemonSelect } from '@posthog/lemon-ui'

import { sceneLogic } from 'scenes/sceneLogic'
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
    const { newTab } = useActions(sceneLogic)

    const hasAtLeastTwoIssues = selectedIds.length >= 2

    const openInNewTabs = (): void => {
        selectedIds.forEach((id) => {
            const issue = issues.find((issue) => issue.id === id)
            if (issue) {
                newTab(urls.errorTrackingIssue(id, { timestamp: issue.last_seen }))
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

    return (
        <div className="flex gap-x-2 justify-between">
            <div className="flex gap-x-2">
                <LemonButton type="secondary" size="small" onClick={openInNewTabs}>
                    Open all
                </LemonButton>
                <LemonButton
                    disabledReason={!hasAtLeastTwoIssues ? 'Select at least two issues to merge' : null}
                    type="secondary"
                    size="small"
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
                </LemonButton>
                <LemonSelect
                    onChange={(value) => {
                        if (value == currentStatus) {
                            return
                        }
                        switch (value) {
                            case 'resolved':
                                resolveIssues(selectedIds)
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
                    value={currentStatus == 'mixed' ? null : currentStatus}
                    placeholder="Mark as"
                    options={options.map((key) => ({
                        value: key,
                        label: <StatusIndicator status={key} size="small" className="w-full" withTooltip={true} />,
                    }))}
                    size="small"
                />
                <AssigneeSelect assignee={null} onChange={(assignee) => assignIssues(selectedIds, assignee)}>
                    {(displayAssignee) => (
                        <LemonButton type="secondary" size="small">
                            <AssigneeLabelDisplay assignee={displayAssignee} placeholder="Assign" />
                        </LemonButton>
                    )}
                </AssigneeSelect>
            </div>
            <LemonButton type="secondary" size="small" onClick={excludeSelectedIssues}>
                Hide from search
            </LemonButton>
        </div>
    )
}
