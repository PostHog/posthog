// The scope boundary: the window controls sit on the panel's rim, and everything inside reflects them.
// The repository is the page's own scope, set from the title. Current-state surfaces belong outside it.

import { ReactNode } from 'react'

import { Spinner } from '@posthog/lemon-ui'

import { ScopeDateFilter } from './ScopeBar'

export function ScopePanel({
    busy = false,
    controls,
    children,
}: {
    /** Reloading with data already on screen, so a window change reads as "updating" rather than a silent swap. */
    busy?: boolean
    /** Rim controls; defaults to the shared window picker. A page with its own window state passes its picker,
     *  and a page with a fixed window passes null. */
    controls?: ReactNode
    children: ReactNode
}): JSX.Element {
    return (
        <div className="relative mt-4 flex flex-col rounded-lg border border-primary p-4">
            <div className="-mt-8 -mr-1 flex max-w-full flex-wrap items-center justify-end gap-2 self-end bg-primary px-2">
                {busy && <Spinner className="text-secondary" />}
                {controls === undefined ? <ScopeDateFilter /> : controls}
            </div>
            <div className="flex flex-col gap-4 pt-2">{children}</div>
        </div>
    )
}
