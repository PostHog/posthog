import React from 'react'

export interface FABGroupProps {
    children: React.ReactNode
}

export function FABGroup({ children }: FABGroupProps): JSX.Element {
    return (
        <div className="flex items-center gap-0.5 px-1.5 py-0.5 bg-surface-primary rounded-full shadow-sm border border-border">
            {children}
        </div>
    )
}
