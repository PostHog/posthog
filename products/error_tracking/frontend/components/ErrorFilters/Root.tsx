import { ReactNode } from 'react'

export const ErrorFiltersRoot = ({ children }: { children: ReactNode }): JSX.Element => {
    return (
        <div className="space-y-1">
            <div className="flex items-center gap-2">{children}</div>
        </div>
    )
}
