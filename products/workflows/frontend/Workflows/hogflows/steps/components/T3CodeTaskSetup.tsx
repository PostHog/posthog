import { useActions, useValues } from 'kea'

import { LemonButton, LemonSelect, Link, Spinner } from '@posthog/lemon-ui'

import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { urls } from 'scenes/urls'

import { CyclotronJobInputType } from '~/types'

import { workflowLogic } from '../../../workflowLogic'
import { t3CodeTaskSetupLogic } from './t3CodeTaskSetupLogic'

const APPROVAL_PROMPTS = {
    projects: 'PostHog needs your OK to read the projects on this machine.',
    task: 'PostHog needs your OK to create the task in T3 Code.',
}

export function T3CodeTaskSetup({
    actionId,
    inputs,
    setInputs,
}: {
    actionId: string
    inputs: Record<string, CyclotronJobInputType>
    setInputs: (inputs: Record<string, CyclotronJobInputType>) => void
}): JSX.Element {
    const logic = t3CodeTaskSetupLogic({
        actionId,
        onWebhookUrl: (webhookUrl) => setInputs({ ...inputs, webhook_url: { value: webhookUrl } }),
    })
    const {
        machines,
        machinesLoading,
        machine,
        projects,
        projectsResultLoading,
        project,
        pendingApproval,
        taskResultLoading,
        createdWebhookUrl,
        error,
    } = useValues(logic)
    const { setMachine, setProject, createTask, allowPendingCall, loadMachines } = useActions(logic)
    const { workflow } = useValues(workflowLogic)

    return (
        <div className="flex flex-col gap-2 rounded border p-3 mb-2">
            <div>
                <div className="font-semibold">Start new threads on a T3 Code machine</div>
                <div className="text-secondary text-xs">
                    Pick a machine and a project. PostHog creates a task there, and each run of this step starts a new
                    thread in that project.
                </div>
            </div>
            {machinesLoading && machines === null ? (
                <Spinner />
            ) : machines?.length === 0 ? (
                <div className="text-xs">
                    No T3 Code machine is connected. In T3 Code, copy the machine's MCP URL from Settings &gt;
                    Environments. Add it in <Link to={urls.settings('mcp-servers')}>MCP servers settings</Link> and
                    approve the sign-in with Supervised access or more.{' '}
                    <Link onClick={() => loadMachines()} data-attr="workflow-t3-code-reload-machines">
                        Check again
                    </Link>
                </div>
            ) : machines ? (
                <>
                    <LemonField.Pure label="Machine">
                        <LemonSelect<string | null>
                            fullWidth
                            value={machine}
                            onChange={setMachine}
                            options={machines.map(({ host, name }) => ({ label: name, value: host }))}
                            placeholder="Choose a machine"
                            data-attr="workflow-t3-code-machine"
                        />
                    </LemonField.Pure>
                    {machine && (
                        <LemonField.Pure label="Project">
                            <LemonSelect<string | null>
                                fullWidth
                                value={project}
                                loading={projectsResultLoading}
                                onChange={setProject}
                                options={(projects ?? []).map(({ id, title, has_default_model }) => ({
                                    label: title,
                                    value: id,
                                    disabledReason: has_default_model
                                        ? undefined
                                        : 'Set a default model for this project in T3 Code first',
                                }))}
                                placeholder={
                                    projects?.length === 0 ? 'This machine has no projects' : 'Choose a project'
                                }
                                disabledReason={projects === null ? 'Load the projects first' : undefined}
                                data-attr="workflow-t3-code-project"
                            />
                        </LemonField.Pure>
                    )}
                </>
            ) : null}
            {pendingApproval && (
                <LemonBanner
                    type="info"
                    action={{
                        children: 'Allow',
                        onClick: allowPendingCall,
                        loading: projectsResultLoading || taskResultLoading,
                        'data-attr': 'workflow-t3-code-allow',
                    }}
                >
                    {APPROVAL_PROMPTS[pendingApproval.kind]}
                </LemonBanner>
            )}
            {error && (
                <LemonBanner
                    type="error"
                    action={
                        machines === null
                            ? {
                                  children: 'Try again',
                                  onClick: loadMachines,
                                  loading: machinesLoading,
                                  'data-attr': 'workflow-t3-code-retry-machines',
                              }
                            : undefined
                    }
                >
                    {error}
                </LemonBanner>
            )}
            {createdWebhookUrl ? (
                <LemonBanner type="success">
                    The task is ready in T3 Code, and the step's webhook URL points to it.
                </LemonBanner>
            ) : pendingApproval?.kind === 'task' ? null : (
                <LemonButton
                    type="secondary"
                    size="small"
                    className="self-start"
                    onClick={() => createTask({ title: `PostHog: ${workflow?.name || 'workflow'}` })}
                    loading={taskResultLoading}
                    disabledReason={!machine ? 'Choose a machine' : !project ? 'Choose a project' : undefined}
                    data-attr="workflow-t3-code-create-task"
                >
                    Create the T3 Code task
                </LemonButton>
            )}
        </div>
    )
}
