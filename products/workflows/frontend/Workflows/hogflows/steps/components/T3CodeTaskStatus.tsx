import { useActions, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { LemonBanner } from 'lib/lemon-ui/LemonBanner'

import { workflowLogic } from '../../../workflowLogic'
import { t3CodeTaskSetupLogic } from './t3CodeTaskSetupLogic'

const APPROVAL_PROMPTS = {
    projects: 'PostHog needs your OK to read the projects on this machine.',
    'more-projects': 'PostHog needs your OK to read more projects on this machine.',
    task: 'PostHog needs your OK to create the task in T3 Code.',
}

export function T3CodeTaskStatus(): JSX.Element {
    const {
        machinesLoading,
        projectsResultLoading,
        pendingApproval,
        callInFlight,
        retry,
        taskResultLoading,
        taskReady,
        createTaskDisabledReason,
        error,
    } = useValues(t3CodeTaskSetupLogic)
    const { createTask, allowPendingCall, loadMachines, loadProjects } = useActions(t3CodeTaskSetupLogic)
    const { workflow } = useValues(workflowLogic)

    return (
        <>
            {pendingApproval && (
                <LemonBanner
                    type="info"
                    action={{
                        children: 'Allow',
                        onClick: allowPendingCall,
                        loading: callInFlight,
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
                        retry === 'machines'
                            ? {
                                  children: 'Try again',
                                  onClick: loadMachines,
                                  loading: machinesLoading,
                                  'data-attr': 'workflow-t3-code-retry-machines',
                              }
                            : retry === 'projects'
                              ? {
                                    children: 'Try again',
                                    onClick: () => loadProjects(undefined),
                                    loading: projectsResultLoading,
                                    'data-attr': 'workflow-t3-code-retry-projects',
                                }
                              : undefined
                    }
                >
                    {error}
                </LemonBanner>
            )}
            {taskReady ? (
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
                    disabledReason={createTaskDisabledReason ?? undefined}
                    data-attr="workflow-t3-code-create-task"
                >
                    Create the T3 Code task
                </LemonButton>
            )}
        </>
    )
}
