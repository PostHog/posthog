import { useValues } from 'kea'

import { IconGitLab } from '@posthog/icons'
import { Link } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { selfDrivingGitlabLogic } from '../../logics/selfDrivingGitlabLogic'

/** The gitlab.com projects Self-driving works in, under the GitHub connection in Code access. */
export function GitlabProjectsList(): JSX.Element | null {
    const { gitlabProjects } = useValues(selfDrivingGitlabLogic)

    if (gitlabProjects.length === 0) {
        return null
    }

    return (
        <div className="flex flex-col gap-2 border-t border-primary pt-3" data-attr="inbox-settings-gitlab-projects">
            <div className="flex flex-col gap-0.5">
                <h4 className="m-0 text-xs font-semibold text-default">GitLab projects</h4>
                <p className="m-0 max-w-2xl text-[11px] leading-snug text-tertiary">
                    Agents can research these projects and open merge requests in them.{' '}
                    <Link to={urls.settings('project-integrations')}>Manage GitLab connections</Link>
                </p>
            </div>
            <ul className="m-0 flex list-none flex-col gap-1 p-0">
                {gitlabProjects.map((project) => (
                    <li key={project} className="flex min-w-0 items-center gap-2 text-xs">
                        <IconGitLab className="size-4 shrink-0" />
                        <span className="min-w-0 truncate font-mono">{project}</span>
                    </li>
                ))}
            </ul>
        </div>
    )
}
