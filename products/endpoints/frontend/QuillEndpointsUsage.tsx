import { useValues } from 'kea'

import { endpointsUsageLogic } from './endpointsUsageLogic'
import { QuillEndpointsUsageContent } from './QuillEndpointsUsageContent'
import { QuillEndpointsUsageFilters } from './QuillEndpointsUsageFilters'

export function QuillEndpointsUsage(): JSX.Element {
    const { refreshKey } = useValues(endpointsUsageLogic)

    return (
        <div className="flex flex-col gap-4" data-quill data-attr="endpoints-usage">
            <QuillEndpointsUsageFilters />
            <QuillEndpointsUsageContent key={refreshKey} />
        </div>
    )
}
