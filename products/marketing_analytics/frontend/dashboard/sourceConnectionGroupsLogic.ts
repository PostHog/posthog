import { MakeLogicType, actions, kea, key, path, props, reducers } from 'kea'

type SourceConnectionGroupsProps = { expansionKey: string }

export const sourceConnectionGroupsLogic = kea<
    MakeLogicType<
        { expandedSourceTypes: string[] | null },
        { setExpandedSourceTypes: (sourceTypes: string[]) => { sourceTypes: string[] } },
        SourceConnectionGroupsProps
    >
>([
    props({} as SourceConnectionGroupsProps),
    key((props) => props.expansionKey),
    path((key) => ['products', 'marketingAnalytics', 'sourceConnectionGroups', key]),
    actions({
        setExpandedSourceTypes: (sourceTypes: string[]) => ({ sourceTypes }),
    }),
    reducers({
        // null until the user toggles a group, so the panel can open its first group by default.
        expandedSourceTypes: [
            null as string[] | null,
            { persist: true },
            { setExpandedSourceTypes: (_, { sourceTypes }) => sourceTypes },
        ],
    }),
])
