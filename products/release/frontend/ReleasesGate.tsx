import { useValues } from 'kea'

import { NotFound } from 'lib/components/NotFound'

import { releaseLogic } from './releaseLogic'

export function ReleasesGate({ children }: { children: JSX.Element }): JSX.Element {
    const { releasesEnabled } = useValues(releaseLogic)

    if (!releasesEnabled) {
        return <NotFound object="Releases" caption="Releases are not enabled for your project." />
    }
    return children
}
