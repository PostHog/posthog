import { LemonBanner } from '@posthog/lemon-ui'

import type { NotebookVariable, NotebookVariableValue } from 'scenes/notebooks/Notebook/notebookVariables'

import type { NotebookAppBlockApi } from '../generated/api.schemas'

function dateInputValue(value: NotebookVariableValue): string {
    if (typeof value !== 'string') {
        return ''
    }
    const date = value.trim()
    const calendar = /^(\d{4})-?(\d{2})-?(\d{2})/.exec(date)
    if (calendar) {
        return calendar.slice(1).join('-')
    }
    const weekDate = /^(\d{4})-?W(\d{2})(?:-?([1-7]))?/.exec(date)
    if (!weekDate) {
        return ''
    }
    const [, year, week, weekday = '1'] = weekDate
    const januaryFourth = new Date(0)
    januaryFourth.setUTCFullYear(Number(year), 0, 4)
    const monday = 4 - ((januaryFourth.getUTCDay() + 6) % 7)
    januaryFourth.setUTCDate(monday + 7 * (Number(week) - 1) + Number(weekday) - 1)
    return januaryFourth.toISOString().slice(0, 10)
}

export function NotebookAppDateRange({
    block,
    variables,
    disabled,
    onChange,
}: {
    block: NotebookAppBlockApi
    variables: NotebookVariable[]
    disabled: boolean
    onChange: (name: string, value: NotebookVariableValue) => void
}): JSX.Element {
    const start = variables.find((v) => v.type === 'date' && v.name === block.variable)
    const end = variables.find((v) => v.type === 'date' && v.name === block.end_variable)
    if (!start || !end || start === end) {
        return <LemonBanner type="warning">Choose two different date variables for this range.</LemonBanner>
    }
    const startDate = dateInputValue(start.value)
    const endDate = dateInputValue(end.value)
    return (
        <fieldset disabled={disabled} className="border-0 p-0 m-0 min-w-0">
            <legend className="font-semibold mb-2">{block.title || 'Date range'}</legend>
            <div className="flex flex-wrap items-center gap-2">
                <label className="flex flex-col gap-1 flex-1 min-w-0">
                    <span>From</span>
                    <input
                        type="date"
                        className="border rounded px-2 py-1 bg-surface-primary min-w-0"
                        value={startDate}
                        max={endDate || undefined}
                        onChange={(event) => {
                            if (event.target.validity.valid) {
                                onChange(start.name, event.target.value || null)
                            }
                        }}
                    />
                </label>
                <label className="flex flex-col gap-1 flex-1 min-w-0">
                    <span>Through</span>
                    <input
                        type="date"
                        className="border rounded px-2 py-1 bg-surface-primary min-w-0"
                        value={endDate}
                        min={startDate || undefined}
                        onChange={(event) => {
                            if (event.target.validity.valid) {
                                onChange(end.name, event.target.value || null)
                            }
                        }}
                    />
                </label>
            </div>
        </fieldset>
    )
}
