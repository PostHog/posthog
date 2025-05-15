import { useActions, useValues } from 'kea'

import { QueryFeature } from '~/queries/nodes/DataTable/queryFeatures'
import { Query } from '~/queries/Query/Query'

import { visionHogEventsSceneLogic } from './visionHogEventsSceneLogic'

export function VisionHogEventsScene(): JSX.Element {
    const { query } = useValues(visionHogEventsSceneLogic)
    const { setQuery } = useActions(visionHogEventsSceneLogic)

    return (
        <Query
            query={query}
            setQuery={setQuery}
            context={{
                showOpenEditorButton: true,
                extraDataTableQueryFeatures: [QueryFeature.highlightExceptionEventRows],
            }}
        />
    )
}
