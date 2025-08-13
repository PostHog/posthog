import { useActions } from 'kea'
import { useEffect } from 'react'

import { errorTrackingReleasesLogic } from './errorTrackingReleasesLogic'
import { ReleasesTable } from './ReleasesTable'

export default function ErrorTrackingReleases(): JSX.Element {
    const { loadReleases } = useActions(errorTrackingReleasesLogic)

    useEffect(() => {
        loadReleases()
    }, [loadReleases])

    return (
        <div className="space-y-4">
            <div>
                <h1 className="text-2xl font-bold">Releases</h1>
                <p className="text-muted">
                    Releases help you track error occurrences across different versions of your application. They are
                    automatically created when you upload source maps or configure error tracking in your application.
                </p>
            </div>
            <ReleasesTable />
        </div>
    )
}
