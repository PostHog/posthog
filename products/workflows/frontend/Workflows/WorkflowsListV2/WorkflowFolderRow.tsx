import { HTMLAttributes, ReactNode } from 'react'

type WorkflowFolderRowProps = {
    icon: JSX.Element
    children: ReactNode
} & Omit<HTMLAttributes<HTMLDivElement>, 'className'>

export function WorkflowFolderRow({ icon, children, ...props }: WorkflowFolderRowProps): JSX.Element {
    return (
        <div className="flex items-center gap-2 min-w-0" {...props}>
            <span className="flex size-6 shrink-0 items-center justify-center text-secondary">{icon}</span>
            {children}
        </div>
    )
}
