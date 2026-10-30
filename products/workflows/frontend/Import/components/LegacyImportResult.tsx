import { useValues } from 'kea'

import { LemonBanner, LemonTag } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'

import { customerIOImportLogic } from '../customerIOImportLogic'

/** The result of an import that ran before imports moved to the background. */
export function LegacyImportResult(): JSX.Element | null {
    const { syncConfig } = useValues(customerIOImportLogic)
    const result = syncConfig?.app_import_result

    if (result?.status === 'failed') {
        return <LemonBanner type="error">Last import failed: {result.error || 'Unknown error'}</LemonBanner>
    }
    if (result?.status !== 'completed') {
        return null
    }
    return (
        <div className="space-y-2 text-sm">
            <LemonBanner type="success">
                <span className="font-semibold">API import complete</span>
            </LemonBanner>
            <div className="flex items-center justify-between">
                <span>Last imported:</span>
                <TZLabel time={result.imported_at} />
            </div>
            <div className="flex items-center justify-between">
                <span>Categories imported:</span>
                <LemonTag>{result.categories_created ?? 0}</LemonTag>
            </div>
            <div className="flex items-center justify-between">
                <span>Globally unsubscribed users:</span>
                <LemonTag>{(result.globally_unsubscribed_count ?? 0).toLocaleString()}</LemonTag>
            </div>
            <div className="flex items-center justify-between">
                <span>Suppressed addresses:</span>
                <LemonTag>{(result.suppressions_imported ?? 0).toLocaleString()}</LemonTag>
            </div>
        </div>
    )
}
