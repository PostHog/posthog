import { MakeLogicType, actions, kea, key, path, props, reducers } from 'kea'

type SourceConnectionGroupsProps = { expansionKey: string }
export type GroupExpansion = { expanded: string[]; seen: string[] }

export function expandedSourceTypes(
    expansion: GroupExpansion | null,
    sourceTypes: string[],
    sourceTypesNeedingAction: string[]
): string[] {
    if (!expansion) {
        const needingAction = sourceTypes.filter((sourceType) => sourceTypesNeedingAction.includes(sourceType))
        return needingAction.length > 0 ? needingAction : sourceTypes.slice(0, 1)
    }
    // Integrations that appeared after the last toggle open, so a new problem is never hidden.
    const unseen = sourceTypes.filter((sourceType) => !expansion.seen.includes(sourceType))
    return sourceTypes.filter((sourceType) => expansion.expanded.includes(sourceType) || unseen.includes(sourceType))
}

export const sourceConnectionGroupsLogic = kea<
    MakeLogicType<
        { expansion: GroupExpansion | null },
        {
            setExpandedSourceTypes: (expanded: string[], seen: string[]) => GroupExpansion
        },
        SourceConnectionGroupsProps
    >
>([
    props({} as SourceConnectionGroupsProps),
    key((props) => props.expansionKey),
    path((key) => ['products', 'marketingAnalytics', 'sourceConnectionGroups', key]),
    actions({
        setExpandedSourceTypes: (expanded: string[], seen: string[]) => ({ expanded, seen }),
    }),
    reducers({
        expansion: [
            null as GroupExpansion | null,
            { persist: true },
            { setExpandedSourceTypes: (_, expansion) => expansion },
        ],
    }),
])
