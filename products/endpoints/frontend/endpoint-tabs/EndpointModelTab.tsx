import { useValues } from 'kea'
import { router } from 'kea-router'

import { LemonBanner, Spinner } from '@posthog/lemon-ui'

import { endpointSceneLogic } from '../endpointSceneLogic'
import { EndpointModelPanel } from './EndpointModelPanel'

export function EndpointModelTab({ tab }: { tab: 'lineage' | 'data-quality' }): JSX.Element {
    const { endpoint, endpointLoading, viewingVersion } = useValues(endpointSceneLogic)
    const { searchParams } = useValues(router)
    const version = viewingVersion ?? endpoint
    const requestedVersion = searchParams.version ? Number(searchParams.version) : endpoint?.current_version
    const displayedVersion = viewingVersion?.version ?? endpoint?.current_version

    if (endpointLoading || (requestedVersion && requestedVersion !== displayedVersion)) {
        return <Spinner />
    }

    if (!version) {
        return <LemonBanner type="error">Couldn't load this version. Reload the endpoint to try again.</LemonBanner>
    }

    if (!version.node_id) {
        return (
            <LemonBanner type="info">
                {version.model_unavailable_reason ||
                    'This version does not have a model yet. Save a new version to create its model.'}
            </LemonBanner>
        )
    }

    return <EndpointModelPanel key={version.node_id} id={version.node_id} tab={tab} />
}
