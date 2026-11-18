import { useTransactionalChannel } from '../useTransactionalChannel'
import { TransactionalEmailLog } from './TransactionalEmailLog'
import { TransactionalPushLog } from './TransactionalPushLog'

/** The Log tab. The Channel filter picks which sends it lists. */
export function TransactionalLog(): JSX.Element {
    const { channel } = useTransactionalChannel()
    return channel === 'push' ? <TransactionalPushLog /> : <TransactionalEmailLog />
}
