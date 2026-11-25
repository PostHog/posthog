import { Fragment } from 'react'

import { TZLabel } from 'lib/components/TZLabel'

import type { HealthReading } from './healthCheckValues'

export function HealthReadingList({ readings }: { readings: HealthReading[] }): JSX.Element {
    return (
        // The label column caps at 16rem, so only the longest setting names wrap and the values stay near their labels.
        <dl className="m-0 grid max-w-2xl grid-cols-[min(16rem,40%)_minmax(0,1fr)] gap-x-6 gap-y-1.5">
            {readings.map((reading) => (
                <Fragment key={reading.label}>
                    <dt className="text-secondary">{reading.label}</dt>
                    {/* Release conditions list one condition set per line. */}
                    <dd className="m-0 tabular-nums whitespace-pre-line">
                        {'time' in reading ? (
                            reading.asDate ? (
                                <TZLabel time={reading.time} formatDate="MMMM D, YYYY" formatTime="h:mm A" />
                            ) : (
                                <TZLabel time={reading.time} />
                            )
                        ) : (
                            reading.text
                        )}
                    </dd>
                </Fragment>
            ))}
        </dl>
    )
}
