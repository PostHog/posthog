import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { LemonButton, LemonSwitch } from '@posthog/lemon-ui'

import { teamLogic } from 'scenes/teamLogic'

import {
    cleanUtmParams,
    getTeamUtmDefaults,
    matchesTeamUtmDefaults,
} from '../../Workflows/hogflows/steps/components/utmDefaults'
import { UtmTagFields, type UtmTagValues } from '../../Workflows/hogflows/steps/components/UtmTagFields'
import { WorkflowsUtmDefaultsApplyDialog } from './WorkflowsUtmDefaultsApplyDialog'
import { workflowsUtmDefaultsApplyLogic } from './workflowsUtmDefaultsApplyLogic'

export function WorkflowsUtmDefaultsSettings(): JSX.Element {
    const { currentTeam, currentTeamLoading } = useValues(teamLogic)
    const { saveDefaults, openApplyDialog } = useActions(workflowsUtmDefaultsApplyLogic)

    const saved = getTeamUtmDefaults(currentTeam?.workflows_config)
    const [enabled, setEnabled] = useState(saved.enabled)
    const [params, setParams] = useState<UtmTagValues>(saved.params)

    useEffect(() => {
        setEnabled(saved.enabled)
        setParams(saved.params)
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [currentTeam?.workflows_config?.email_utm_tags_enabled, JSON.stringify(saved.params)])

    const unchanged = enabled === saved.enabled && matchesTeamUtmDefaults(params, saved)

    return (
        <div className="flex flex-col gap-2 max-w-160">
            <LemonSwitch
                id="workflows-email-utm-defaults"
                checked={enabled}
                onChange={setEnabled}
                label="Add UTM tags to links in new emails"
                bordered
                data-attr="workflows-utm-defaults-toggle"
            />
            <UtmTagFields
                value={params}
                onChange={setParams}
                campaignDefault="Broadcast or workflow name"
                contentDefault="Email step name"
            />
            <div className="flex gap-2">
                <LemonButton
                    type="primary"
                    size="small"
                    loading={currentTeamLoading}
                    disabledReason={unchanged ? 'No changes to save' : undefined}
                    onClick={() => {
                        const valuesChanged = !matchesTeamUtmDefaults(params, saved)
                        saveDefaults(enabled, cleanUtmParams(params), valuesChanged || (enabled && !saved.enabled))
                    }}
                    data-attr="workflows-utm-defaults-save"
                >
                    Save
                </LemonButton>
                <LemonButton
                    type="secondary"
                    size="small"
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
