import { type ReactNode } from 'react'

export function TwoColumns({ children }: { children: ReactNode }): JSX.Element {
    return <div className="grid min-w-0 grid-cols-1 gap-4 @min-[64rem]/mcp-overview:grid-cols-2">{children}</div>
}
