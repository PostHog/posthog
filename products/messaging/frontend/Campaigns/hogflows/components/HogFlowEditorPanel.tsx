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
                'react-flow__panel flex flex-col bottom top',
                className,
                position.includes('right') ? 'right' : 'left',
                position.includes('bottom') ? 'justify-end' : 'justify-start'
            )}
        >
            <div
                className={clsx(
                    'flex z-10 flex-col max-h-full rounded-md border shadow-lg bg-surface-primary',
                    className
                )}
            >
                {children}
            </div>
        </div>
    )
}
