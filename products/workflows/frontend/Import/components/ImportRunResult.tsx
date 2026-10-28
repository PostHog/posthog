import { LemonBanner } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'

import type { ProviderImportRunApi } from 'products/messaging/frontend/generated/api.schemas'

import { CustomerIOImportRunProgress } from './CustomerIOImportRunProgress'

export function ImportRunResult({ run }: { run: ProviderImportRunApi }): JSX.Element {
    return (
        <div className="space-y-3">
            {run.status === 'completed' ? (
                <LemonBanner type="success">
                    <span className="font-semibold">Import finished</span>
                </LemonBanner>
            ) : (
                <LemonBanner type="error">
                    Some steps failed. Run the import again to retry them. Data that already imported isn't duplicated.
                </LemonBanner>
            )}
            <CustomerIOImportRunProgress run={run} />
            {run.finished_at && (
                <div className="flex items-center justify-between text-sm">
                    <span>Finished</span>
                    <TZLabel time={run.finished_at} />
                </div>
            )}
        </div>
    )
}
