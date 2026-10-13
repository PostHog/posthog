// The header and row of a settings table. Every table on the Settings tab shares them, so the
// Project and Mine columns line up from one table to the next. Below 48rem the header hides and
// each row stacks into one column.
export const SETTINGS_HEADER =
    'hidden gap-3 px-4 py-1.5 text-xxs font-semibold uppercase tracking-wide text-secondary @min-[48rem]:grid @min-[48rem]:grid-cols-[minmax(0,1fr)_minmax(0,16rem)_minmax(0,18rem)]'
export const SETTINGS_ROW =
    'grid grid-cols-1 gap-2 border-t border-primary px-4 py-3 @min-[48rem]:grid-cols-[minmax(0,1fr)_minmax(0,16rem)_minmax(0,18rem)] @min-[48rem]:gap-3'
