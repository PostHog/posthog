import { MakeLogicType, actions, kea, key, path, props, reducers, selectors } from 'kea'

type SourceConnectionGroupsProps = { expansionKey: string; sourceTypes: string[]; sourceTypesNeedingAction?: string[] }
type GroupExpansion = { expanded: string[]; seen: string[] }

export const sourceConnectionGroupsLogic = kea<
    MakeLogicType<
        { expansion: GroupExpansion | null; expandedSourceTypes: string[] },
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
    selectors({
        expandedSourceTypes: [
            (s, p) => [s.expansion, p.sourceTypes, p.sourceTypesNeedingAction],
            (
                expansion: GroupExpansion | null,
                sourceTypes: string[],
                sourceTypesNeedingAction: string[] | undefined
            ): string[] => {
                if (!expansion) {
                    const needingAction = sourceTypes.filter((sourceType) =>
                        sourceTypesNeedingAction?.includes(sourceType)
                    )
                    return needingAction.length > 0 ? needingAction : sourceTypes.slice(0, 1)
                }
                // Integrations that appeared after the last toggle open, so a new problem is never hidden.
                const unseen = sourceTypes.filter((sourceType) => !expansion.seen.includes(sourceType))
                return sourceTypes.filter(
                    (sourceType) => expansion.expanded.includes(sourceType) || unseen.includes(sourceType)
                )
            },
        ],
    }),
])
