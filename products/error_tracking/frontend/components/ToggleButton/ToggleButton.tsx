import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { cn } from 'lib/utils/css-classes'

export interface ToggleButtonPrimitiveProps {
    className?: string
    checked: boolean
    children: React.ReactNode
    tooltip?: string
    iconOnly?: boolean
    onCheckedChange: (checked: boolean) => void
}

export function ToggleButtonPrimitive({
    className,
    checked,
    tooltip,
    children,
    iconOnly,
    onCheckedChange,
}: ToggleButtonPrimitiveProps): JSX.Element {
    return (
        <ButtonPrimitive
            iconOnly={iconOnly}
            tooltip={tooltip}
            className={cn(
                className,
                checked
                    ? 'not-disabled:bg-zinc-700 not-disabled:hover:bg-zinc-700 dark:not-disabled:bg-zinc-300 dark:not-disabled:hover:bg-zinc-300 text-foreground-inverse'
                    : ''
            )}
            onClick={() => onCheckedChange(!checked)}
        >
            {children}
        </ButtonPrimitive>
    )
}
