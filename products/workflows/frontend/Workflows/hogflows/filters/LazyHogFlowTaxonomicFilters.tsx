import { Suspense } from 'react'

import type { TaxonomicFilterRenderProps } from 'lib/components/TaxonomicFilter/types'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { lazyWithRetry } from 'lib/utils/retryImport'

// The workflow variables tab needs workflowLogic, which pulls in liquid and the hog function
// configuration logic. The taxonomic filter logic is on the path of every logged-in page, so load
// the tab only when it renders.
const HogFlowTaxonomicFilters = lazyWithRetry(() =>
    import('./HogFlowTaxonomicFilters').then((m) => ({ default: m.HogFlowTaxonomicFilters }))
)

export function LazyHogFlowTaxonomicFilters(props: TaxonomicFilterRenderProps): JSX.Element {
    return (
        <Suspense fallback={<Spinner />}>
            <HogFlowTaxonomicFilters {...props} />
        </Suspense>
    )
}
