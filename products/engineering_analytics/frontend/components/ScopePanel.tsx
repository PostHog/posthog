// The scope boundary: the source and window controls sit on the panel's rim, and everything inside
// reflects them. Current-state surfaces belong outside it.

import { ReactNode } from 'react'

import { Spinner } from '@posthog/lemon-ui'

import { ScopeDateFilter, SourceScopeChip } from './ScopeBar'

export function ScopePanel({
    busy = false,
    children,
}: {
    /** Reloading with data already on screen, so a window change reads as "updating" rather than a silent swap. */
    busy?: boolean
    children: ReactNode
}): JSX.Element {
    return (
        <div className="relative mt-4 rounded-lg border border-primary p-4">
            <div className="absolute -top-4 right-3 flex flex-wrap items-center justify-end gap-2 bg-primary px-2">
                {busy && <Spinner className="text-secondary" />}
                <SourceScopeChip pickerOnly />
                <ScopeDateFilter />
            </div>
            <div className="flex flex-col gap-4 pt-2">{children}</div>
        </div>
    )
}
