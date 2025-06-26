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
            <div
                className={clsx(
                    'flex z-10 flex-col max-h-full m-2 rounded-md border shadow-lg bg-surface-primary overflow-hidden',
                    className
                )}
            >
                {children}
            </div>
        </div>
    )
}
