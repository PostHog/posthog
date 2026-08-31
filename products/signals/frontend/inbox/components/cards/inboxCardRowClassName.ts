import clsx from 'clsx'

/**
 * Shared row className for inbox cards. Attached rows sit inside a single bordered container
 * (dividers between items); freestanding cards get their own border (dashed for reports).
 * `success` swaps the surface for the success tint (resolved reports read as finished work),
 * so it replaces the default background and its hover shade rather than fighting them.
 */
export function inboxCardRowClassName(attached: boolean, opts?: { dashed?: boolean; success?: boolean }): string {
    return clsx(
        'group flex w-full flex-col gap-2.5 @lg:flex-row @lg:items-stretch @lg:gap-3 px-4 py-3.5 transition-all duration-150',
        opts?.success ? 'bg-success-highlight' : 'bg-surface-primary hover:bg-surface-secondary',
        attached
            ? 'border-b border-primary last:border-b-0'
            : opts?.dashed
              ? 'rounded border border-dashed border-primary hover:border-secondary'
              : 'rounded border border-primary hover:border-secondary'
    )
}
