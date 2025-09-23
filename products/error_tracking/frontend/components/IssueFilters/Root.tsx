import { ReactNode } from 'react'

export const ErrorFiltersRoot = ({ children }: { children: ReactNode }): JSX.Element => {
    return <div className="space-y-2">{children}</div>
}
