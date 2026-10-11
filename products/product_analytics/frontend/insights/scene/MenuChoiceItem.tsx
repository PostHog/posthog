import { DropdownMenuRadioItem, cn } from '@posthog/quill'

export function MenuChoiceItem({
    className,
    ...props
}: React.ComponentProps<typeof DropdownMenuRadioItem>): JSX.Element {
    return (
        <DropdownMenuRadioItem
            className={cn('ps-2 [&>[data-slot=dropdown-menu-radio-item-indicator]]:hidden', className)}
            {...props}
        />
    )
}
