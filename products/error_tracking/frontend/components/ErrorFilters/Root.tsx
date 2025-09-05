import { ReactNode } from 'react'

export const ErrorFiltersRoot = ({ children }: { children: ReactNode }): JSX.Element => {
    return (
        <div className="space-y-1">
            <div className="flex flex-col gap-2 border rounded p-2 bg-white">{children}</div>
        </div>
    )
}
