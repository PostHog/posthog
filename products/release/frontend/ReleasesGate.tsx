import { useValues } from 'kea'

import { NotFound } from 'lib/components/NotFound'

import { releaseLogic } from './releaseLogic'

export function ReleasesGate({ children, area = false }: { children: JSX.Element; area?: boolean }): JSX.Element {
    const { releasesEnabled, releasesAreaEnabled } = useValues(releaseLogic)

    if (!(area ? releasesAreaEnabled : releasesEnabled)) {
        return <NotFound object="Releases" caption="Releases are not enabled for your project." />
    }
    return children
}
