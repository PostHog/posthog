import { ReactNode } from 'react'

import { Spinner } from '@posthog/lemon-ui'

/** The panel is the scope: the controls sit on its rim, and everything inside reflects
 *  them. Content a picker does not govern belongs outside the panel. */
export function ScopePanel({
    controls,
    busy = false,
    children,
}: {
    controls: ReactNode
    busy?: boolean
    children: ReactNode
}): JSX.Element {
    return (
        <div className="relative mt-4 rounded-lg border border-primary p-4">
            <div className="absolute -top-4 right-3 flex flex-wrap items-center justify-end gap-2 bg-primary px-2">
                {busy && <Spinner className="text-secondary" />}
                {controls}
            </div>
            <div className="flex flex-col gap-4 pt-2">{children}</div>
        </div>
    )
}
