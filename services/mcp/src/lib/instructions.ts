import type { GroupType } from '@/api/client'
import { formatPrompt } from '@/lib/utils'
import type { CachedOrg, CachedProject, CachedUser } from '@/tools/types'

export function buildGroupTypesBlock(groupTypes?: GroupType[]): string {
    if (!groupTypes || groupTypes.length === 0) {
        return ''
    }
    const lines = groupTypes.map((gt) => {
        const names = [gt.name_singular, gt.name_plural].filter(Boolean)
        const suffix = names.length > 0 ? ` (${names.join(' / ')})` : ''
        return `- Index ${gt.group_type_index}: "${gt.group_type}"${suffix}`
    })
    return `### Group type mapping\n\nGroups aggregate events based on entities, such as organizations or sellers. This project has the following group types. Instead of a group's name, always use its numeric index.\n\n${lines.join('\n')}`
}

export function buildActiveEnvironmentContextPrompt(
    user?: CachedUser,
    org?: CachedOrg,
    project?: CachedProject
): string | undefined {
    if (!user && !org && !project) {
        return undefined
    }
    const lines: string[] = []
    if (org || project) {
        const projectName = project?.name ?? 'Unknown'
        const projectId = project?.id ?? 'unknown'
        const orgName = org?.name ?? 'Unknown'
        const orgId = org?.id ?? 'unknown'
        lines.push(
            `You are currently in project "${projectName}" (id: ${projectId}) within organization "${orgName}" (id: ${orgId}).`
        )
    }
    if (project) {
        lines.push(`Project timezone: ${project.timezone ?? 'UTC'}.`)
        const poeValue = project.person_on_events_querying_enabled as string | boolean | null | undefined
        if (poeValue === true || poeValue === 'true') {
            lines.push(
                'Person-on-events mode is enabled. When querying `person.properties.*` on the events table, values reflect what was set at the time the event was ingested, not the person\'s current value. The same person can have different property values across different events. Do not suggest workarounds for "query-time" person properties.'
            )
        } else {
            lines.push(
                "Person properties are query-time in this project. `person.properties.*` on the events table always returns the person's current (latest) value, regardless of when the event occurred."
            )
        }
    }
    if (user) {
        const fullName = [user.first_name, user.last_name].filter(Boolean).join(' ') || 'Unknown'
        lines.push(`The user's name is ${fullName} (${user.email}).`)
    }
    return `### Active environment\n\nAll tool calls and queries are scoped to this environment.\n\n${lines.join('\n')}`
}

export function buildInstructionsV1(template: string, metadata?: string): string {
    if (!metadata) {
        return template
    }
    return `${template}\n\n${metadata}`
}

export function buildInstructionsV2(
    template: string,
    guidelines: string,
    groupTypes?: GroupType[],
    metadata?: string
): string {
    return formatPrompt(template, {
        guidelines: guidelines.trim(),
        group_types: buildGroupTypesBlock(groupTypes),
        metadata: metadata?.trim() ?? '',
    })
}
