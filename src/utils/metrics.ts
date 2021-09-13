import * as Sentry from '@sentry/node'
import { StatsD, Tags } from 'hot-shots'

export async function instrumentQuery<T>(
    statsd: StatsD | undefined,
    metricName: string,
    tag: string | undefined,
    runQuery: () => Promise<T>
): Promise<T> {
    const tags: Tags | undefined = tag ? { queryTag: tag } : undefined
    const timer = new Date()

    statsd?.increment(`${metricName}.total`, tags)
    try {
        return await runQuery()
    } catch (error) {
        Sentry.captureException(error, { extra: { query_tag: tag } })
        throw error
    } finally {
        statsd?.timing(metricName, timer, tags)
    }
}
