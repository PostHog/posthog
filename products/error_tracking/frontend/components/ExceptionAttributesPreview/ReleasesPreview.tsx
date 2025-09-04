import { ExceptionRelease } from 'lib/components/Errors/types'

import { ReleaseTag } from './ReleaseTag'
import { ReleasesPopoverContent } from './ReleasesPopoverContent'

export function ReleasesPreview({ releases }: { releases?: ExceptionRelease[] }): JSX.Element {
    if (!releases || releases.length === 0) {
        return <></>
    }

    const overlay = <ReleasesPopoverContent releases={releases} />

    if (releases.length === 1) {
        const commitShaShortened = releases[0].commitSha.slice(0, 7)
        return <ReleaseTag title={commitShaShortened} overlay={overlay} />
    }

    return <ReleaseTag title={`${releases.length} related releases`} overlay={overlay} />
}
