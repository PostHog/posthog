import { Tooltip } from '@posthog/lemon-ui'

import type { DataAgeLabel } from '../suggestionCopy'

export interface DataAgeMetaProps {
    age: DataAgeLabel
}

export function DataAgeMeta({ age }: DataAgeMetaProps): JSX.Element {
    if (!age.caveat) {
        return <span translate="no">{age.label}</span>
    }
    return (
        <Tooltip title={age.caveat}>
            <span tabIndex={0} className="cursor-help underline decoration-dotted underline-offset-2">
                <span translate="no">{age.label}</span>
                <span className="sr-only">{`. ${age.caveat}`}</span>
            </span>
        </Tooltip>
    )
}
