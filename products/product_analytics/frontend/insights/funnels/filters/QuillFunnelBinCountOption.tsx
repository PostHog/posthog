import { useEffect, useId, useRef, useState } from 'react'

import {
    Button,
    Field,
    InputGroup,
    InputGroupAddon,
    InputGroupInput,
    InputGroupText,
    Select,
    SelectContent,
    SelectItem,
    SelectSeparator,
    SelectTrigger,
    SelectValue,
} from '@posthog/quill'

import { QuillChartOptionLabel } from 'lib/components/ChartOptions/QuillChartOptionLabel'
import { BIN_COUNT_AUTO } from 'lib/constants'

// Limits from the time to convert query on the backend.
const MIN_BINS = 1
const MAX_BINS = 90
const PRESETS = [5, 15, 25, 50, 90]
const CUSTOM = 'custom'

type BinChoice = number | typeof BIN_COUNT_AUTO | typeof CUSTOM

export function QuillFunnelBinCountOption({
    value,
    onChange,
    disabledReason,
}: {
    value: number | undefined
    onChange: (binCount: number | undefined) => void
    disabledReason?: string | null
}): JSX.Element {
    const id = useId()
    const [draft, setDraft] = useState<string | null>(null)
    const [customPicked, setCustomPicked] = useState(false)
    const inputRef = useRef<HTMLInputElement>(null)
    const editing = draft !== null

    useEffect(() => {
        if (!editing) {
            return
        }
        // The closing list hands focus back to its trigger after this field mounts.
        const frame = requestAnimationFrame(() => inputRef.current?.focus())
        return () => cancelAnimationFrame(frame)
    }, [editing])
    const counts = [...new Set([...PRESETS, ...(value === undefined ? [] : [value])])].sort((a, b) => a - b)

    const commit = (): void => {
        const parsed = draft === null ? NaN : parseInt(draft, 10)
        if (parsed >= MIN_BINS && parsed <= MAX_BINS) {
            onChange(parsed)
        }
        setDraft(null)
    }

    return (
        <Field orientation="horizontal" className="justify-between">
            <QuillChartOptionLabel htmlFor={id} label="Bins" />
            {draft !== null ? (
                <InputGroup className="w-28">
                    <InputGroupInput
                        id={id}
                        type="text"
                        inputMode="numeric"
                        ref={inputRef}
                        value={draft}
                        placeholder={`${MIN_BINS}-${MAX_BINS}`}
                        onChange={(event) => setDraft(event.target.value)}
                        onBlur={commit}
                        onKeyDown={(event) => {
                            if (event.key === 'Enter') {
                                commit()
                            } else if (event.key === 'Escape') {
                                event.stopPropagation()
                                setDraft(null)
                            }
                        }}
                        data-attr="funnel-bin-count-custom"
                    />
                    <InputGroupAddon align="inline-end">
                        <InputGroupText>bins</InputGroupText>
                    </InputGroupAddon>
                </InputGroup>
            ) : (
                <Select<BinChoice>
                    value={value ?? BIN_COUNT_AUTO}
                    onValueChange={(next: BinChoice | null) => {
                        if (next === CUSTOM) {
                            setCustomPicked(true)
                        } else if (next !== null) {
                            onChange(next === BIN_COUNT_AUTO ? undefined : next)
                        }
                    }}
                    onOpenChangeComplete={(open: boolean) => {
                        if (!open && customPicked) {
                            setCustomPicked(false)
                            setDraft(value === undefined ? '' : String(value))
                        }
                    }}
                    disabled={!!disabledReason}
                >
                    <SelectTrigger
                        id={id}
                        render={<Button variant="outline" left disabledReason={disabledReason || undefined} />}
                        data-attr="funnel-bin-count"
                    >
                        <SelectValue>
                            {(selected: BinChoice) => (selected === BIN_COUNT_AUTO ? 'Auto' : `${selected} bins`)}
                        </SelectValue>
                    </SelectTrigger>
                    <SelectContent align="start" alignItemWithTrigger={false}>
                        <SelectItem value={BIN_COUNT_AUTO}>Auto</SelectItem>
                        {counts.map((count) => (
                            <SelectItem key={count} value={count}>
                                {count} bins
                            </SelectItem>
                        ))}
                        <SelectSeparator />
                        <SelectItem value={CUSTOM}>Custom…</SelectItem>
                    </SelectContent>
                </Select>
            )}
        </Field>
    )
}
