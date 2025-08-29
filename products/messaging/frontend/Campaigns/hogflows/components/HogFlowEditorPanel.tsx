import clsx from 'clsx'

export type HogFlowEditorPanelProps = {
    position: 'right-bottom' | 'left-bottom' | 'right-top' | 'left-top'
    children: React.ReactNode
    width?: number | string
}

export function HogFlowEditorPanel({ position, children, width }: HogFlowEditorPanelProps): JSX.Element {
    return (
        <div
            className={clsx(
                'absolute flex flex-col m-0 p-2 overflow-hidden transition-[width] max-h-full',
                position.includes('right') ? 'right-0' : 'left-0',
                position.includes('bottom') ? 'justify-end' : 'justify-start'
            )}
            style={{ width }}
        >
            <div
                className="relative flex flex-col rounded-md overflow-hidden bg-surface-primary max-h-full z-10"
                style={{
                    border: '1px solid var(--border)',
                    boxShadow: '0 3px 0 var(--border)',
                    zIndex: 0,
                }}
            >
                {children}
            </div>
        </div>
    )
}
