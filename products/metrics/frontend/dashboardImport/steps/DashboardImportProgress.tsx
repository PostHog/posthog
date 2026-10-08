import { useValues } from 'kea'

import { Spinner } from '@posthog/lemon-ui'

import { metricsDashboardImportLogic } from '../metricsDashboardImportLogic'

export function DashboardImportProgress(): JSX.Element {
    const { currentImport } = useValues(metricsDashboardImportLogic)

    return (
        <div className="flex flex-col items-center gap-3 py-8 text-center">
            <Spinner className="text-3xl" />
            <div className="font-semibold">
                {currentImport ? `Importing "${currentImport.dashboard_name}"` : 'Getting the status of the import'}
            </div>
            <div className="text-secondary">
                {currentImport?.progress ||
                    'PostHog AI matches the panels to the metrics, logs and traces of this project.'}
            </div>
            <div className="max-w-md text-xs text-secondary">
                An import usually takes a few minutes. You can close this window. The import continues, and a message
                shows when the dashboard is ready.
            </div>
        </div>
    )
}
