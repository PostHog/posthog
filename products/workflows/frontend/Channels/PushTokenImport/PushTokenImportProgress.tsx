import { useValues } from 'kea'

import { LemonBanner } from '@posthog/lemon-ui'

import { LemonProgress } from 'lib/lemon-ui/LemonProgress'

import { pushTokenImportLogic } from './pushTokenImportLogic'

/** Shows how far a running import has got. */
export function PushTokenImportProgress(): JSX.Element | null {
    const { currentImport, isStopping, error } = useValues(pushTokenImportLogic)
    if (!currentImport) {
        return null
    }
    const { processed_devices: sent, total_devices: total } = currentImport

    return (
        <div className="flex flex-col gap-2">
            <span>
                <span>{isStopping ? 'Stopping the import…' : 'Importing devices…'}</span>{' '}
                <span translate="no">{sent.toLocaleString()}</span> of{' '}
                <span translate="no">{total.toLocaleString()}</span> sent.
            </span>
            <LemonProgress percent={total ? (sent / total) * 100 : 0} />
            {error ? <LemonBanner type="error">{error}</LemonBanner> : null}
            <span className="text-xs text-secondary">
                The import keeps running if you close this window. Open it again to see the result.
            </span>
        </div>
    )
}
