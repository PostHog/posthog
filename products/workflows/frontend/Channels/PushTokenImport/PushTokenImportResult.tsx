import { useValues } from 'kea'

import { LemonBanner } from '@posthog/lemon-ui'

import { pluralize } from 'lib/utils/strings'

import { PushTokenFailedRowsTable } from './PushTokenFailedRowsTable'
import { pushTokenImportLogic } from './pushTokenImportLogic'
import { PushTokenImportOutcomeBanner } from './PushTokenImportOutcomeBanner'

/** Shows what a finished import stored and which lines it could not import. */
export function PushTokenImportResult(): JSX.Element | null {
    const { currentImport, error } = useValues(pushTokenImportLogic)
    if (!currentImport) {
        return null
    }
    const { failures, failed_devices, unknown_person_devices } = currentImport

    return (
        <>
            <PushTokenImportOutcomeBanner job={currentImport} />
            {error ? <LemonBanner type="error">{error}</LemonBanner> : null}
            {currentImport.can_import_unknown_persons ? (
                <span className="text-sm">
                    {unknown_person_devices.toLocaleString()}{' '}
                    {pluralize(unknown_person_devices, 'device has', 'devices have', false)} a distinct ID that no
                    person in PostHog has. Check that it's the ID your app passes to identify. If the IDs are right,
                    import them anyway to create those persons.
                </span>
            ) : null}
            {failures.length > 0 ? <PushTokenFailedRowsTable rows={failures} /> : null}
            {failed_devices > failures.length ? (
                <span className="text-xs text-secondary">
                    The table shows the first {failures.length.toLocaleString()} lines that were not imported.
                </span>
            ) : null}
        </>
    )
}
