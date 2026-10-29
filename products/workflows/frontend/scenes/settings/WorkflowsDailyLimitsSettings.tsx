import { useActions, useMountedLogic, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { teamLogic } from 'scenes/teamLogic'

import { TeamType } from '~/types'

import { unsavedSettingsLogic } from './unsavedSettingsLogic'

type WorkflowsConfig = NonNullable<TeamType['workflows_config']>
type LimitField = {
    [Key in keyof WorkflowsConfig]-?: NonNullable<WorkflowsConfig[Key]> extends number ? Key : never
}[keyof WorkflowsConfig]

export interface WorkflowsDailyLimitsSettingsProps {
    perWorkflowField: LimitField
    perProjectField: LimitField
    defaultPerWorkflow: number
    defaultPerProject: number
    /** What the limits count, in the plural, such as "tasks". */
    unit: string
    /** Prefix for the inputs' ids and `data-attr`s. */
    attrPrefix: string
}

// Kept in step with the ceilings on TeamWorkflowsConfigSerializer, which reject anything higher.
const SELF_SERVE_MULTIPLIER = 5

// A cleared number input reports NaN, which must save as null to restore the default.
function toInputValue(limit: number | null | undefined): number | null {
    return typeof limit === 'number' && Number.isFinite(limit) ? limit : null
}

export function WorkflowsDailyLimitsSettings({
    perWorkflowField,
    perProjectField,
    defaultPerWorkflow,
    defaultPerProject,
    unit,
    attrPrefix,
}: WorkflowsDailyLimitsSettingsProps): JSX.Element {
    const { currentTeam, currentTeamLoading } = useValues(teamLogic)
    const { updateCurrentTeam } = useActions(teamLogic)
    const unsavedGuard = unsavedSettingsLogic({
        sectionId: attrPrefix,
        message: `Leave without saving?\nThe ${unit} limits you entered will be discarded.`,
    })
    // useActions alone does not mount a logic, and the guard arms on mount.
    useMountedLogic(unsavedGuard)
    const { setHasUnsavedChanges } = useActions(unsavedGuard)
    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })

    const savedPerWorkflow = toInputValue(currentTeam?.workflows_config?.[perWorkflowField])
    const savedPerProject = toInputValue(currentTeam?.workflows_config?.[perProjectField])

    const [perWorkflow, setPerWorkflow] = useState<number | null>(savedPerWorkflow)
    const [perProject, setPerProject] = useState<number | null>(savedPerProject)

    useEffect(() => {
        setPerWorkflow(savedPerWorkflow)
        setPerProject(savedPerProject)
    }, [savedPerWorkflow, savedPerProject])

    const errorFor = (limit: number | null, saved: number | null, max: number): string | undefined => {
        if (limit === null) {
            return undefined
        }
        if (!Number.isInteger(limit)) {
            return 'Enter a whole number'
        }
        if (limit < 0) {
            return 'A limit cannot be negative'
        }
        // Support can set a value above the ceiling; leaving it untouched is not an error.
        if (limit > max && limit !== saved) {
            return `Contact support to go above ${max.toLocaleString()} ${unit} a day`
        }
        return undefined
    }

    const maxPerWorkflow = defaultPerWorkflow * SELF_SERVE_MULTIPLIER
    const maxPerProject = defaultPerProject * SELF_SERVE_MULTIPLIER
    const perWorkflowError = errorFor(perWorkflow, savedPerWorkflow, maxPerWorkflow)
    const perProjectError = errorFor(perProject, savedPerProject, maxPerProject)
    const unchanged = perWorkflow === savedPerWorkflow && perProject === savedPerProject

    useEffect(() => {
        setHasUnsavedChanges(!unchanged)
    }, [unchanged, setHasUnsavedChanges])

    return (
        <div className="@container">
            <div className="flex flex-wrap gap-4">
                <LemonField.Pure
                    className="flex-1 min-w-60"
                    label="Per workflow"
                    htmlFor={`${attrPrefix}-limit-per-workflow`}
                    help={`Leave empty to use the default of ${defaultPerWorkflow}.`}
                    error={perWorkflowError}
                >
                    <LemonInput
                        id={`${attrPrefix}-limit-per-workflow`}
                        type="number"
                        min={0}
                        max={maxPerWorkflow}
                        value={perWorkflow ?? undefined}
                        onChange={(value) => setPerWorkflow(toInputValue(value))}
                        placeholder={`${defaultPerWorkflow}`}
                        disabledReason={restrictedReason}
                        data-attr={`${attrPrefix}-limit-per-workflow`}
                    />
                </LemonField.Pure>
                <LemonField.Pure
                    className="flex-1 min-w-60"
                    label="Across the project"
                    htmlFor={`${attrPrefix}-limit-per-project`}
                    help={`Leave empty to use the default of ${defaultPerProject}.`}
                    error={perProjectError}
                >
                    <LemonInput
                        id={`${attrPrefix}-limit-per-project`}
                        type="number"
                        min={0}
                        max={maxPerProject}
                        value={perProject ?? undefined}
                        onChange={(value) => setPerProject(toInputValue(value))}
                        placeholder={`${defaultPerProject}`}
                        disabledReason={restrictedReason}
                        data-attr={`${attrPrefix}-limit-per-project`}
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
                                capture_workflows_engagement_events:
                                    currentTeam?.workflows_config?.capture_workflows_engagement_events ?? false,
                                [perWorkflowField]: perWorkflow,
                                [perProjectField]: perProject,
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
                    data-attr={`${attrPrefix}-limits-save`}
                >
                    Save
                </LemonButton>
            </div>
        </div>
    )
}
