import { MakeLogicType, afterMount, kea, key, path, props } from 'kea'
import { loaders } from 'kea-loaders'

import { performQuery } from '~/queries/query'

import { LaneUsage, UsageTarget, parseUsage, usageQueries } from './releaseLaneUsage'

export interface ReleaseLaneUsageLogicProps {
    target: UsageTarget
    from: string
}

interface ReleaseLaneUsageLogicValues {
    usage: LaneUsage | null
    usageLoading: boolean
}

interface ReleaseLaneUsageLogicActions {
    loadUsage: () => void
    loadUsageSuccess: (usage: LaneUsage | null) => { usage: LaneUsage | null }
    loadUsageFailure: (error: string) => { error: string }
}

type releaseLaneUsageLogicType = MakeLogicType<
    ReleaseLaneUsageLogicValues,
    ReleaseLaneUsageLogicActions,
    ReleaseLaneUsageLogicProps
>

export const releaseLaneUsageLogic = kea<releaseLaneUsageLogicType>([
    props({} as ReleaseLaneUsageLogicProps),
    key(({ target, from }) => `${target.kind}:${target.value}:${from}`),
    path((logicKey) => ['products', 'release', 'frontend', 'releaseLaneUsageLogic', logicKey]),
    loaders(({ props }) => ({
        usage: [
            null as LaneUsage | null,
            {
                loadUsage: async () => {
                    const queries = usageQueries(props.target, props.from)
                    const [daily, week, split] = await Promise.all([
                        performQuery(queries.daily),
                        performQuery(queries.week),
                        performQuery(queries.split),
                    ])
                    return parseUsage(
                        props.target.kind,
                        (daily.results ?? []) as unknown[][],
                        (week.results ?? []) as unknown[][],
                        (split.results ?? []) as unknown[][]
                    )
                },
            },
        ],
    })),
    afterMount(({ actions }) => {
        actions.loadUsage()
    }),
])
