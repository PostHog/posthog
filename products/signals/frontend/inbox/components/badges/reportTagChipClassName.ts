import clsx from 'clsx'

/** A report tag chip, styled like the meta text around it, on the inbox cards and the report page. */
export function reportTagChipClassName(selected: boolean): string {
    return clsx(
        'inline-flex min-w-0 max-w-40 items-center rounded px-1 py-1 text-xs leading-none',
        selected
            ? 'bg-accent-highlight-secondary font-medium text-accent'
            : 'text-tertiary hover:bg-fill-button-tertiary-hover hover:text-primary'
    )
}
