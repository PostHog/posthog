import clsx from 'clsx'

export type HogFlowEditorPanelProps = {
    position: 'right-bottom' | 'left-bottom' | 'right-top' | 'left-top'
    children: React.ReactNode
}

export function HogFlowEditorPanel({ position, children }: HogFlowEditorPanelProps): JSX.Element {
    return (
        <div
            className={clsx(
                'react-flow__panel flex flex-col top max-h-full m-0',
                position.includes('right') ? 'right' : 'left',
                position.includes('bottom') ? 'justify-end' : 'justify-start'
            )}
        >
            <div className="relative flex z-10 flex-col max-h-full m-2 rounded bg-surface-primary">
                <div
                    className="relative z-10 flex flex-col flex-1 rounded-md overflow-hidden"
                    style={{
                        border: '1px solid var(--border)',
                        boxShadow: '0 3px 0 var(--border)',
                        zIndex: 0,
                    }}
                >
                    {children}
                </div>
            </div>
        </div>
    )
}
