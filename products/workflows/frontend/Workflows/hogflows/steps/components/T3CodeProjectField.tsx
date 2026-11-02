import { useActions, useValues } from 'kea'

import { LemonButton, LemonSelect, Link } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import { t3CodeTaskSetupLogic } from './t3CodeTaskSetupLogic'

export function T3CodeProjectField(): JSX.Element {
    const {
        projects,
        projectsResultLoading,
        moreProjectsResultLoading,
        project,
        pendingApproval,
        projectHelp,
        projectDisabledReason,
    } = useValues(t3CodeTaskSetupLogic)
    const { setProject, loadProjects, loadMoreProjects } = useActions(t3CodeTaskSetupLogic)

    return (
        <LemonField.Pure
            label="Project"
            help={
                projectHelp === 'more-projects' ? (
                    <div className="flex items-center gap-1">
                        Showing {projects?.length} projects. This machine has more.
                        <LemonButton
                            type="tertiary"
                            size="xsmall"
                            onClick={() => loadMoreProjects(undefined)}
                            loading={moreProjectsResultLoading}
                            disabledReason={
                                pendingApproval?.kind === 'more-projects'
                                    ? 'Allow PostHog to read more projects first'
                                    : undefined
                            }
                            data-attr="workflow-t3-code-more-projects"
                        >
                            Load more projects
                        </LemonButton>
                    </div>
                ) : projectHelp === 'no-default-model' ? (
                    <>
                        T3 Code starts threads only in a project with a default model. Set one in the project's settings
                        in T3 Code.{' '}
                        <Link onClick={() => loadProjects(undefined)} data-attr="workflow-t3-code-reload-projects">
                            Check again
                        </Link>
                    </>
                ) : undefined
            }
        >
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
                placeholder={projects?.length === 0 ? 'This machine has no projects' : 'Choose a project'}
                disabledReason={projectDisabledReason ?? undefined}
                data-attr="workflow-t3-code-project"
            />
        </LemonField.Pure>
    )
}
