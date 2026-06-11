import { useActions, useValues } from 'kea'

import { LemonButton, LemonMenu } from '@posthog/lemon-ui'

import {
    AssigneeIconDisplay,
    AssigneeLabelDisplay,
} from 'products/error_tracking/frontend/components/Assignee/AssigneeDisplay'
import { AssigneeSelect } from 'products/error_tracking/frontend/components/Assignee/AssigneeSelect'
import { ErrorFilters } from 'products/error_tracking/frontend/components/IssueFilters'
import { STATUS_OPTIONS, statusOptionLabel } from 'products/error_tracking/frontend/components/IssueFilters/Status'
import { issueQueryOptionsLogic } from 'products/error_tracking/frontend/components/IssueQueryOptions/issueQueryOptionsLogic'

import { ERROR_TRACKING_SCENE_LOGIC_KEY } from '../../../errorTrackingSceneLogic'
import { ListReloadButton } from '../IssuesList'
import { OmniBar, QUICK_FILTER_CONTEXT } from './OmniBar'
import { SortDirectionButton, SortFieldButton } from './SortButtons'

/**
 * Variant F — "Token bar".
 * The whole query state lives inline: date, status, and assignee are
 * always-visible tokens at the start of the input (no hunting for current
 * scope), property chips flow after them, and arrangement tokens sit at the
 * right edge. One row, one surface, everything uniform xsmall.
 */
export function IssuesFiltersF(): JSX.Element {
    return (
        <OmniBar
            showIssueChips={false}
            prefixTokens={
                <>
                    <ErrorFilters.DateRange size="xsmall" type="tertiary" />
                    <StatusToken />
                    <AssigneeToken />
                    <div className="w-px h-4 bg-border shrink-0 mx-0.5" />
                </>
            }
            trailing={
                <>
                    <SortFieldButton size="xsmall" />
                    <SortDirectionButton size="xsmall" />
                    <ErrorFilters.SettingsMenu
                        size="xsmall"
                        quickFilterContext={QUICK_FILTER_CONTEXT}
                        logicKey={ERROR_TRACKING_SCENE_LOGIC_KEY}
                    />
                    <ListReloadButton size="xsmall" />
                </>
            }
        />
    )
}

const StatusToken = (): JSX.Element => {
    const { status } = useValues(issueQueryOptionsLogic)
    const { setStatus } = useActions(issueQueryOptionsLogic)
    const currentStatus = status ?? 'active'

    return (
        <LemonMenu
            items={STATUS_OPTIONS.map((option) => ({
                label: statusOptionLabel(option),
                active: currentStatus === option,
                onClick: () => setStatus(option),
            }))}
        >
            <LemonButton size="xsmall" type="tertiary" tooltip="Status">
                {statusOptionLabel(currentStatus)}
            </LemonButton>
        </LemonMenu>
    )
}

const AssigneeToken = (): JSX.Element => {
    const { assignee } = useValues(issueQueryOptionsLogic)
    const { setAssignee } = useActions(issueQueryOptionsLogic)

    return (
        <AssigneeSelect assignee={assignee ?? null} onChange={(value) => setAssignee(value)}>
            {(displayAssignee) => (
                <LemonButton size="xsmall" type="tertiary" tooltip="Assignee">
                    <span className="flex items-center gap-1 min-w-0">
                        <AssigneeIconDisplay assignee={displayAssignee} size="xsmall" />
                        <AssigneeLabelDisplay
                            assignee={displayAssignee}
                            placeholder="Anyone"
                            size="xsmall"
                            className="truncate"
                        />
                    </span>
                </LemonButton>
            )}
        </AssigneeSelect>
    )
}
