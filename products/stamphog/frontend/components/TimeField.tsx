import { TZLabel } from 'lib/components/TZLabel'

import { Field } from './Field'

export function TimeField({ label, time }: { label: string; time?: string | null }): JSX.Element {
    return <Field label={label}>{time ? <TZLabel time={time} /> : null}</Field>
}
