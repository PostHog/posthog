import type { ReactNode } from 'react'

/** A row that opens nothing. It copies the height, gap and sizes of the xsmall button rows, so both kinds line up. */
export function HealthCheckPlainRow({ icon, children }: { icon: JSX.Element; children: ReactNode }): JSX.Element {
    return (
        <li className="flex items-center gap-1 min-h-[1.625rem] pl-0.5 text-xs">
            <span className="flex shrink-0 text-sm">{icon}</span>
            {children}
        </li>
    )
}
