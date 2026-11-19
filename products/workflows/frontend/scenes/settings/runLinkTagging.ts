import { TeamPublicType, TeamType } from '~/types'

export function runLinkTaggingEnabled(team: TeamPublicType | TeamType | null): boolean {
    return team?.workflows_config?.email_workflow_run_link_tag_enabled ?? true
}
