/**
 * Whether the active session can create a project.
 *
 * `project-create` posts to an organization endpoint that three backend gates
 * guard: the plan's project allowance, the caller's membership level, and the
 * credential's project scoping. None of them is visible to the agent, so it
 * asks the user, gets approval, and only then learns the create was
 * impossible. This module reproduces the gates to tell the agent up front. It
 * fails open: an unknown state returns `undefined`, which leaves the tool
 * exactly as it is today.
 */

/** Mirrors `AvailableFeature.ORGANIZATIONS_PROJECTS`. */
const PROJECTS_FEATURE_KEY = 'organizations_projects'
/** Mirrors `AvailableFeature.ORGANIZATION_INVITE_SETTINGS`. */
const INVITE_SETTINGS_FEATURE_KEY = 'organization_invite_settings'
/** Mirrors `OrganizationMembership.Level.ADMIN`. */
const ADMIN_MEMBERSHIP_LEVEL = 8
/** Orgs without the projects entitlement get one non-demo project. */
const UNENTITLED_PROJECT_ALLOWANCE = 1

/** Only `available_product_features` is in the generated org schema today, so
 * the fields this reads are declared structurally. */
export interface ProjectCreationOrgFields {
    available_product_features?: Array<{ key?: string | null; limit?: number | null }> | null
    teams?: Array<{ project_id?: number | null; is_demo?: boolean | null }> | null
    membership_level?: number | null
    members_can_create_projects?: boolean | null
}

export interface ProjectCreationInput {
    org: ProjectCreationOrgFields | undefined
    /** Project ids the credential is restricted to, empty when unrestricted. */
    scopedTeams: number[]
}

function findFeature(
    org: ProjectCreationOrgFields,
    key: string
): { key?: string | null; limit?: number | null } | undefined {
    const features = org.available_product_features
    if (!Array.isArray(features)) {
        return undefined
    }
    return features.find((feature) => feature?.key === key)
}

/** Non-demo projects the caller can see, counted the way the backend counts them. */
function countProjectsInUse(org: ProjectCreationOrgFields): number | undefined {
    const teams = org.teams
    if (!Array.isArray(teams)) {
        return undefined
    }
    const projectIds = new Set<number>()
    for (const team of teams) {
        if (team?.is_demo || typeof team?.project_id !== 'number') {
            continue
        }
        projectIds.add(team.project_id)
    }
    return projectIds.size
}

/**
 * Returns a sentence for the agent when project creation cannot succeed, or
 * `undefined` when it can or when the session cannot tell.
 */
export function resolveProjectCreationBlock({ org, scopedTeams }: ProjectCreationInput): string | undefined {
    if (scopedTeams.length > 0) {
        return 'Project creation is unavailable in this session: the credential is restricted to specific projects, and creating a project is an organization-level action. Tell the user to reconnect with a credential that covers the whole organization. Do not call this tool.'
    }

    if (!org) {
        return undefined
    }

    // Check membership before the plan allowance, in the same order as the backend, because a plan
    // upgrade alone does not let a member without create access create a project.
    const level = org.membership_level
    if (typeof level === 'number' && level < ADMIN_MEMBERSHIP_LEVEL) {
        const membersMayCreate =
            !!findFeature(org, INVITE_SETTINGS_FEATURE_KEY) && org.members_can_create_projects === true
        if (!membersMayCreate) {
            return 'Project creation is unavailable in this session: only organization admins can create projects here. Tell the user to ask an organization admin, and do not call this tool.'
        }
    }

    const inUse = countProjectsInUse(org)
    if (inUse !== undefined) {
        const feature = findFeature(org, PROJECTS_FEATURE_KEY)
        const allowance = feature ? feature.limit : UNENTITLED_PROJECT_ALLOWANCE
        if (typeof allowance === 'number' && inUse >= allowance) {
            return `Project creation is unavailable in this session: this organization's plan includes ${allowance} project${allowance === 1 ? '' : 's'} and ${inUse} ${inUse === 1 ? 'is' : 'are'} in use. Tell the user they need to upgrade the organization's plan first, and do not call this tool until they have.`
        }
    }

    return undefined
}

export const PROJECT_CREATE_TOOL_NAME = 'project-create'

/**
 * Appends the block to `project-create`'s advertised description, so the agent
 * reads it before it asks the user to approve a create that cannot succeed.
 * The tool stays listed: the block is a best-effort read of the org, and a
 * caller that goes ahead anyway still gets the API's own denial.
 */
export function withProjectCreationBlock<T extends { name: string; description?: string | undefined }>(
    tools: T[],
    block: string | undefined
): T[] {
    if (!block) {
        return tools
    }
    return tools.map((tool) =>
        tool.name === PROJECT_CREATE_TOOL_NAME ? { ...tool, description: `${tool.description}\n\n${block}` } : tool
    )
}
