import { useActions, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { LemonRadio } from 'lib/lemon-ui/LemonRadio'

import { slackAppWorkspaceSetupLogic } from '../slackAppWorkspaceSetupLogic'

export function DefaultProjectStep(): JSX.Element {
    const { setup, selectedProjectIntegrationId, savingDefaultProject } = useValues(slackAppWorkspaceSetupLogic)
    const { selectProject, saveDefaultProject, skipStep } = useActions(slackAppWorkspaceSetupLogic)

    return (
        <>
            <div className="flex flex-col items-center gap-1 text-center">
                <h1 className="text-2xl font-bold m-0">Which project should PostHog use by default?</h1>
                <p className="text-secondary m-0">
                    This Slack workspace is connected to more than one project. PostHog uses the default project when a
                    question doesn't name one. Each person can change it for themselves in Slack.
                </p>
            </div>

            <LemonRadio
                className="w-full"
                aria-label="Default project"
                value={selectedProjectIntegrationId}
                onChange={selectProject}
                options={(setup?.project_options ?? []).map((option) => ({
                    value: option.integration_id,
                    label: option.project_name,
                    description: option.organization_name,
                }))}
            />

            <div className="flex flex-wrap justify-between items-center gap-2 w-full">
                <LemonButton type="tertiary" onClick={() => skipStep('default_project')}>
                    Skip
                </LemonButton>
                <LemonButton
                    type="primary"
                    loading={savingDefaultProject}
                    onClick={saveDefaultProject}
                    data-attr="slack-app-workspace-setup-save-default-project"
                >
                    Use this project
                </LemonButton>
            </div>
        </>
    )
}
