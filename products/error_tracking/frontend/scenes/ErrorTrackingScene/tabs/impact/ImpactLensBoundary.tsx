import { ErrorBoundary } from '~/layout/ErrorBoundary'

import type { ImpactView } from './impactTabLogic'

// A result stored by an older version of a lens can miss fields that rendering reads. The boundary contains that
// error to what it wraps, instead of the whole error tracking scene. The reset key changes when a lens is
// calculated again, which clears the error.
export function ImpactLensBoundary({
    view,
    resetKey,
    children,
}: {
    view: ImpactView
    resetKey: string
    children: React.ReactNode
}): JSX.Element {
    return (
        <ErrorBoundary key={`${view}-${resetKey}`} exceptionProps={{ lens_type: view }} className="m-3">
            {children}
        </ErrorBoundary>
    )
}
