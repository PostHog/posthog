import { actions, kea, path, reducers } from 'kea'

import { DateRange } from '~/queries/schema/schema-general'

import type { logsDateRangePickerLogicType } from './logsDateRangePickerLogicType'

const MAX_HISTORY_ITEMS = 5

const dateRangesEqual = (a: DateRange, b: DateRange): boolean => a.date_from === b.date_from && a.date_to === b.date_to

export const logsDateRangePickerLogic = kea<logsDateRangePickerLogicType>([
    path(['products', 'logs', 'frontend', 'filters', 'LogsDateRangePicker', 'logsDateRangePickerLogic']),
    actions({
        setPopoverOpen: (open: boolean) => ({ open }),
        setCustomFrom: (value: string) => ({ value }),
        setCustomTo: (value: string) => ({ value }),
        addToHistory: (dateRange: DateRange) => ({ dateRange }),
    }),
    reducers({
        popoverOpen: [
            false,
            {
                setPopoverOpen: (_, { open }) => open,
            },
        ],
        customFrom: [
            '',
            {
                setCustomFrom: (_, { value }) => value,
            },
        ],
        customTo: [
            'now',
            {
                setCustomTo: (_, { value }) => value,
            },
        ],
        history: [
            [] as DateRange[],
            { persist: true },
            {
                addToHistory: (state, { dateRange }) => {
                    const filtered = state.filter((h) => !dateRangesEqual(h, dateRange))
                    return [dateRange, ...filtered].slice(0, MAX_HISTORY_ITEMS)
                },
            },
        ],
    }),
])
