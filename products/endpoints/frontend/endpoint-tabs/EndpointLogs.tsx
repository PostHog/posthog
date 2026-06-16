import { useValues } from 'kea'

import { LogsViewer } from 'scenes/hog-functions/logs/LogsViewer'

import { endpointSceneLogic } from '../endpointSceneLogic'

export function EndpointLogs(): JSX.Element {
    const { endpoint } = useValues(endpointSceneLogic)

    if (!endpoint) {
        return <></>
    }

    return (
        <LogsViewer sourceType="endpoints" sourceId={endpoint.id} groupByInstanceId={false} instanceLabel="execution" />
    )
}
