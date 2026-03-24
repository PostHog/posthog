import type { GroupType } from '@/api/client'
import { formatPrompt } from '@/lib/utils'

export function buildGroupTypesBlock(groupTypes?: GroupType[]): string {
    if (!groupTypes || groupTypes.length === 0) {
        return ''
    }
    const lines = groupTypes.map(
        (gt) => `- Index ${gt.group_type_index}: "${gt.group_type}"${gt.name_singular ? ` (${gt.name_singular})` : ''}`
    )
    return `### Group type mapping\n\nGroups aggregate events based on entities, such as organizations or sellers. This project has the following group types. Instead of a group's name, always use its numeric index.\n\n${lines.join('\n')}`
}

export function buildInstructionsV2(template: string, guidelines: string, groupTypes?: GroupType[]): string {
    return formatPrompt(template, {
        guidelines: guidelines.trim(),
        group_types: buildGroupTypesBlock(groupTypes),
    })
}
