import { Fragment } from 'react'

import { TZLabel } from 'lib/components/TZLabel'

import type { HealthReading } from './healthCheckValues'

export function HealthReadingList({ readings }: { readings: HealthReading[] }): JSX.Element {
    return (
        <dl className="m-0 grid max-w-xl grid-cols-2 gap-x-4 gap-y-1.5">
            {readings.map((reading) => (
                <Fragment key={reading.label}>
                    <dt className="text-secondary">{reading.label}</dt>
                    <dd className="m-0 tabular-nums">
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
