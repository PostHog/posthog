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
                'react-flow__panel top m-0 flex max-h-full flex-col',
                className,
                position.includes('right') ? 'right' : 'left',
                position.includes('bottom') ? 'justify-end' : 'justify-start'
            )}
        >
            <div
                className={clsx(
                    'bg-surface-primary z-10 m-2 flex max-h-full flex-col overflow-hidden rounded-md border shadow-lg',
                    className
                )}
            >
                {children}
            </div>
        </div>
    )
}
