import clsx from 'clsx'

/**
 * Shared row className for inbox cards. Attached rows sit inside a single bordered container
 * (dividers between items); freestanding cards get their own border (dashed for reports).
 */
export function inboxCardRowClassName(attached: boolean, opts?: { dashed?: boolean }): string {
    return clsx(
        'group flex w-full flex-col gap-2.5 @lg:flex-row @lg:items-stretch @lg:gap-3 bg-surface-primary px-4 py-3.5 transition-all duration-150 hover:bg-surface-secondary',
        attached
            ? 'border-b border-primary last:border-b-0'
            : opts?.dashed
              ? 'rounded border border-dashed border-primary hover:border-secondary'
              : 'rounded border border-primary hover:border-secondary'
    )
}
