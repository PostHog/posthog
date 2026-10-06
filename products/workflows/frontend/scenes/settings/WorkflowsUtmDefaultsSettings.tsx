import { useActions, useValues } from 'kea'

import { LemonButton, LemonSwitch } from '@posthog/lemon-ui'

import { teamLogic } from 'scenes/teamLogic'

import { UtmTagFields } from '../../Workflows/hogflows/steps/components/UtmTagFields'
import { WorkflowsUtmDefaultsApplyDialog } from './WorkflowsUtmDefaultsApplyDialog'
import { workflowsUtmDefaultsApplyLogic } from './workflowsUtmDefaultsApplyLogic'

export function WorkflowsUtmDefaultsSettings(): JSX.Element {
    const { currentTeam, currentTeamLoading } = useValues(teamLogic)
    const { form, hasUnsavedChanges } = useValues(workflowsUtmDefaultsApplyLogic)
    const { setDraftEnabled, setDraftParams, saveDefaults, openApplyDialog } =
        useActions(workflowsUtmDefaultsApplyLogic)

    return (
        <div className="flex flex-col gap-2 max-w-160">
            <LemonSwitch
                id="workflows-email-utm-defaults"
                checked={form.enabled}
                onChange={setDraftEnabled}
                label="Add UTM tags to links in new emails"
                bordered
                data-attr="workflows-utm-defaults-toggle"
            />
            <UtmTagFields
                value={form.params}
                onChange={setDraftParams}
                campaignDefault="Broadcast or workflow name"
                contentDefault="Email step name"
            />
            <div className="flex gap-2">
                <LemonButton
                    type="primary"
                    size="small"
                    loading={currentTeamLoading}
                    disabledReason={
                        !currentTeam?.workflows_config
                            ? 'Loading your workflow settings'
                            : hasUnsavedChanges
                              ? undefined
                              : 'No changes to save'
                    }
                    onClick={saveDefaults}
                    data-attr="workflows-utm-defaults-save"
                >
                    Save
                </LemonButton>
                <LemonButton
                    type="secondary"
                    size="small"
                    disabledReason={hasUnsavedChanges ? 'Save your changes first' : undefined}
                    onClick={openApplyDialog}
                    data-attr="workflows-utm-defaults-apply-existing"
                >
                    Apply to existing emails
                </LemonButton>
            </div>
            <WorkflowsUtmDefaultsApplyDialog />
        </div>
    )
}
