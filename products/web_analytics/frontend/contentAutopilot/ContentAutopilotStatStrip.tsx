import clsx from 'clsx'

// The border color shows through the 1px gaps, so cells are divided on every row and column at any width.
export const ContentAutopilotStatStrip = ({
    children,
    className,
    'data-attr': dataAttr,
}: {
    children: React.ReactNode
    className: string
    'data-attr': string
}): JSX.Element => (
    <div
        className={clsx(
            'grid gap-px border rounded-lg bg-border-primary overflow-hidden [&>*]:bg-surface-primary',
            className
        )}
        data-attr={dataAttr}
    >
        {children}
    </div>
)
