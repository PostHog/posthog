import { useActions, useValues } from 'kea'

import { LemonButton, LemonInput } from '@posthog/lemon-ui'

import { engineeringAnalyticsFiltersLogic } from '../scenes/engineeringAnalyticsFiltersLogic'

// Quick presets for the default branch. We can't tell main from master without another query, so offer
// both — clicking the active one clears back to all branches.
const DEFAULT_BRANCHES = ['main', 'master']

/** Branch scope control (server-side head_branch filter), shared by the Workflows tab and a single
 *  workflow's detail page so the scope carries between them. Reads/writes the shared filters logic; typing
 *  stages the value and Enter/blur (or a chip) applies it. */
export function BranchFilter(): JSX.Element {
    const { branchInput, appliedBranch } = useValues(engineeringAnalyticsFiltersLogic)
    const { setBranchFilter, applyBranchFilter } = useActions(engineeringAnalyticsFiltersLogic)

    // Stage + apply a branch in one click (the chips). Clicking the active chip clears back to all branches.
    const selectBranch = (branch: string): void => {
        setBranchFilter(branch)
        applyBranchFilter()
    }

    return (
        <>
            <LemonInput
                type="search"
                size="small"
                className="w-56"
                placeholder="Branch: all (e.g. main)"
                value={branchInput}
                onChange={setBranchFilter}
                onPressEnter={applyBranchFilter}
                onBlur={applyBranchFilter}
                data-attr="engineering-analytics-branch-filter"
            />
            {DEFAULT_BRANCHES.map((branch) => (
                <LemonButton
                    key={branch}
                    size="xsmall"
                    type={appliedBranch === branch ? 'primary' : 'secondary'}
                    // Keep focus on the input so its onBlur doesn't fire first and apply whatever was
                    // staged there — a chip should apply exactly its own branch, in one reload.
                    onMouseDown={(e) => e.preventDefault()}
                    onClick={() => selectBranch(appliedBranch === branch ? '' : branch)}
                >
                    {branch}
                </LemonButton>
            ))}
        </>
    )
}
