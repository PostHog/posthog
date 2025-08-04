import clsx from 'clsx'

export type HogFlowEditorPanelProps = {
    position: 'right-bottom' | 'left-bottom' | 'right-top' | 'left-top'

    className?: string
    children: React.ReactNode
}

export function HogFlowEditorPanel({ className, position, children }: HogFlowEditorPanelProps): JSX.Element {
    return (
        <div
            className={clsx(
                'react-flow__panel flex flex-col top max-h-full m-0',
                className,
                position.includes('right') ? 'right' : 'left',
                position.includes('bottom') ? 'justify-end' : 'justify-start'
            )}
        >
            <div className={clsx('relative flex z-10 flex-col max-h-full m-2', className)}>
                <div
                    className="absolute -inset-px rounded-md pointer-events-none"
                    style={{
                        border: '1px solid var(--border)',
                        zIndex: 0,
                    }}
                />
                <div
                    className="absolute rounded-md pointer-events-none bg-surface-primary"
                    style={{
                        inset: '-1px -1px 3px',
                        border: '1px solid var(--border)',
                        boxShadow: '0 4px 0 -1px var(--border-primary)',
                        zIndex: 0,
                    }}
                />
                <div className="relative z-10 flex flex-col flex-1 rounded-md overflow-hidden">{children}</div>
            </div>
        </div>
    )
}
