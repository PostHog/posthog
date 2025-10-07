import { useValues } from 'kea'

import { Query } from '~/queries/Query/Query'

import { errorTrackingBreakdownsSceneLogic } from './errorTrackingBreakdownsSceneLogic'

export function BreakdownChart(): JSX.Element {
    const { breakdownQuery } = useValues(errorTrackingBreakdownsSceneLogic)

    return (
        <div className="border rounded bg-surface-primary p-3">
            <Query query={breakdownQuery} />
        </div>
    )
}
