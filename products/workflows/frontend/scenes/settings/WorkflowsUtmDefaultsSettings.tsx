import { useActions, useValues } from 'kea'

import { LemonButton, LemonSwitch } from '@posthog/lemon-ui'
import { Button, Field, FieldLabel, Switch } from '@posthog/quill'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { teamLogic } from 'scenes/teamLogic'

import { QuillUtmTagFields } from '../../Workflows/hogflows/steps/components/QuillUtmTagFields'
import { UtmTagFields } from '../../Workflows/hogflows/steps/components/UtmTagFields'
import { WorkflowsUtmDefaultsApplyDialog } from './WorkflowsUtmDefaultsApplyDialog'
import { workflowsUtmDefaultsApplyLogic } from './workflowsUtmDefaultsApplyLogic'
import { workflowsUtmDefaultsSettingsLogic } from './workflowsUtmDefaultsSettingsLogic'

export function WorkflowsUtmDefaultsSettings(): JSX.Element {
    const { currentTeam, currentTeamLoading } = useValues(teamLogic)
    const { form, hasUnsavedChanges } = useValues(workflowsUtmDefaultsSettingsLogic)
    const { setDraftEnabled, setDraftParams, saveDefaults } = useActions(workflowsUtmDefaultsSettingsLogic)
    const { openApplyDialog } = useActions(workflowsUtmDefaultsApplyLogic)
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    const saveDisabledReason = !currentTeam?.workflows_config
        ? 'Loading your workflow settings'
        : hasUnsavedChanges
          ? undefined
          : 'No changes to save'
    const applyDisabledReason = hasUnsavedChanges ? 'Save your changes first' : undefined

    if (todayRailNav) {
        return (
            <div className="flex flex-col gap-2 max-w-160">
                <Field orientation="horizontal" className="w-fit">
                    <Switch
                        id="workflows-email-utm-defaults"
                        checked={form.enabled}
                        onCheckedChange={setDraftEnabled}
                        data-attr="workflows-utm-defaults-toggle"
                    />
                    <FieldLabel htmlFor="workflows-email-utm-defaults">Add UTM tags to links in new emails</FieldLabel>
                </Field>
                <QuillUtmTagFields
                    value={form.params}
                    onChange={setDraftParams}
                    campaignDefault="Broadcast or workflow name"
                    contentDefault="Email step name"
                />
                <div className="flex flex-wrap gap-2">
                    <Button
                        variant="primary"
                        loading={currentTeamLoading}
                        disabledReason={saveDisabledReason}
                        onClick={saveDefaults}
                        data-attr="workflows-utm-defaults-save"
                    >
                        Save
                    </Button>
                    <Button
                        variant="outline"
                        disabledReason={applyDisabledReason}
                        onClick={openApplyDialog}
                        data-attr="workflows-utm-defaults-apply-existing"
                    >
                        Apply to existing emails
                    </Button>
                </div>
                <WorkflowsUtmDefaultsApplyDialog />
            </div>
        )
    }

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
                    disabledReason={saveDisabledReason}
                    onClick={saveDefaults}
                    data-attr="workflows-utm-defaults-save"
                >
                    Save
                </LemonButton>
                <LemonButton
                    type="secondary"
                    size="small"
                    disabledReason={applyDisabledReason}
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
