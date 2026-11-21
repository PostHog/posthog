import { TransactionalChannelSelect } from '../TransactionalChannelSelect'
import { useTransactionalChannel } from '../useTransactionalChannel'
import { TransactionalEmailMetrics } from './TransactionalEmailMetrics'
import { TransactionalEmailMetricsDateRange } from './TransactionalEmailMetricsDateRange'
import { TransactionalPushMetrics } from './TransactionalPushMetrics'

/** The Metrics tab. Email and push count different things, so the channel picker shows one at a time. */
export function TransactionalMetrics(): JSX.Element {
    const { channel } = useTransactionalChannel()
    const actions = (
        <div className="flex items-center gap-2">
            <TransactionalChannelSelect dataAttr="transactional-metrics-channel-filter" />
            <TransactionalEmailMetricsDateRange />
        </div>
    )
    return channel === 'push' ? (
        <TransactionalPushMetrics actions={actions} />
    ) : (
        <TransactionalEmailMetrics actions={actions} />
    )
}
