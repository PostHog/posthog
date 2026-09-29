import { getRuntimeFromLib } from 'lib/components/Errors/utils'

import { RuntimeIcon } from '../RuntimeIcon'
import { FingerprintSample } from './fingerprintSamplesLogic'

interface FingerprintLabelProps {
    fingerprint: string
    sample?: FingerprintSample
}

export function FingerprintLabel({ fingerprint, sample }: FingerprintLabelProps): JSX.Element {
    const runtime = getRuntimeFromLib(sample?.lib)

    return (
        <span className="grid w-full min-w-0 grid-cols-[0.75rem_minmax(0,1fr)] items-center gap-x-2 gap-y-0.5">
            <RuntimeIcon runtime={runtime} fontSize="0.75rem" />
            {sample ? (
                <>
                    <span className="min-w-0 truncate text-left font-semibold">{sample.type}</span>
                    <span className="col-span-2 min-w-0 truncate text-left text-muted-foreground">{sample.value}</span>
                </>
            ) : (
                <span className="min-w-0 truncate text-left font-mono">{fingerprint}</span>
            )}
        </span>
    )
}
