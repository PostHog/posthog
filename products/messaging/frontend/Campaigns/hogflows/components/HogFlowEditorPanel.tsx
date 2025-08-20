import clsx from 'clsx'

export type HogFlowEditorPanelProps = {
    position: 'right-bottom' | 'left-bottom' | 'right-top' | 'left-top'
    children: React.ReactNode
}

export function HogFlowEditorPanel({ position, children }: HogFlowEditorPanelProps): JSX.Element {
    return (
        <div
            className={clsx(
                'react-flow__panel flex flex-col top-2 bottom-2 right-2 m-0 pb-2 overflow-hidden',
                position.includes('right') ? 'right' : 'left',
                position.includes('bottom') ? 'justify-end' : 'justify-start'
            )}
        >
            <div className="relative flex flex-col z-10 rounded bg-surface-primary max-h-full">
                <div
                    className="flex flex-col rounded-md overflow-hidden"
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
