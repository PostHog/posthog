import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { teamLogic } from 'scenes/teamLogic'

const DEFAULT_PER_WORKFLOW_LIMIT = 100
const DEFAULT_PER_PROJECT_LIMIT = 500
// Kept in step with the ceilings on TeamWorkflowsConfigSerializer, which reject anything higher.
const MAX_PER_WORKFLOW_LIMIT = DEFAULT_PER_WORKFLOW_LIMIT * 5
const MAX_PER_PROJECT_LIMIT = DEFAULT_PER_PROJECT_LIMIT * 5

function toInputValue(limit: number | null | undefined): number | null {
    return typeof limit === 'number' ? limit : null
}

export function WorkflowsTaskLimitsSettings(): JSX.Element {
    const { currentTeam, currentTeamLoading } = useValues(teamLogic)
    const { updateCurrentTeam } = useActions(teamLogic)
    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })

    const savedPerWorkflow = toInputValue(currentTeam?.workflows_config?.workflow_task_rate_limit_per_day)
    const savedPerProject = toInputValue(currentTeam?.workflows_config?.workflow_task_team_rate_limit_per_day)

    const [perWorkflow, setPerWorkflow] = useState<number | null>(savedPerWorkflow)
    const [perProject, setPerProject] = useState<number | null>(savedPerProject)

    const errorFor = (limit: number | null, max: number): string | undefined => {
        if (limit === null) {
            return undefined
        }
        if (Number.isNaN(limit) || !Number.isInteger(limit)) {
            return 'Enter a whole number'
        }
        if (limit < 0) {
            return 'A limit cannot be negative'
        }
        if (limit > max) {
            return `Contact support to go above ${max.toLocaleString()} tasks a day`
        }
        return undefined
    }

    const perWorkflowError = errorFor(perWorkflow, MAX_PER_WORKFLOW_LIMIT)
    const perProjectError = errorFor(perProject, MAX_PER_PROJECT_LIMIT)
    const unchanged = perWorkflow === savedPerWorkflow && perProject === savedPerProject

    return (
        <div className="@container">
            <div className="flex flex-wrap gap-4">
                <LemonField.Pure
                    className="flex-1 min-w-60"
                    label="Per workflow"
                    help={`Leave empty to use the default of ${DEFAULT_PER_WORKFLOW_LIMIT}.`}
                    error={perWorkflowError}
                >
                    <LemonInput
                        type="number"
                        min={0}
                        max={MAX_PER_WORKFLOW_LIMIT}
                        value={perWorkflow ?? undefined}
                        onChange={(value) => setPerWorkflow(value ?? null)}
                        placeholder={`${DEFAULT_PER_WORKFLOW_LIMIT}`}
                        disabledReason={restrictedReason}
                        data-attr="workflows-task-limit-per-workflow"
                    />
                </LemonField.Pure>
                <LemonField.Pure
                    className="flex-1 min-w-60"
                    label="Across the project"
                    help={`Leave empty to use the default of ${DEFAULT_PER_PROJECT_LIMIT}.`}
                    error={perProjectError}
                >
                    <LemonInput
                        type="number"
                        min={0}
                        max={MAX_PER_PROJECT_LIMIT}
                        value={perProject ?? undefined}
                        onChange={(value) => setPerProject(value ?? null)}
                        placeholder={`${DEFAULT_PER_PROJECT_LIMIT}`}
                        disabledReason={restrictedReason}
                        data-attr="workflows-task-limit-per-project"
                    />
                </LemonField.Pure>
            </div>
            <div className="mt-4">
                <LemonButton
                    type="primary"
                    loading={currentTeamLoading}
                    onClick={() =>
                        updateCurrentTeam({
                            workflows_config: {
                                ...currentTeam?.workflows_config,
                                capture_workflows_engagement_events:
                                    currentTeam?.workflows_config?.capture_workflows_engagement_events ?? false,
                                workflow_task_rate_limit_per_day: perWorkflow,
                                workflow_task_team_rate_limit_per_day: perProject,
                            },
                        })
                    }
                    disabledReason={
                        restrictedReason ??
                        (perWorkflowError || perProjectError
                            ? 'Fix the limits above to save'
                            : unchanged
                              ? 'No changes to save'
                              : currentTeamLoading
                                ? 'Saving'
                                : undefined)
                    }
                    data-attr="workflows-task-limits-save"
                >
                    Save
                </LemonButton>
            </div>
        </div>
    )
}
