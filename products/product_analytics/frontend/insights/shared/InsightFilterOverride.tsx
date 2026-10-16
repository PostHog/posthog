import type { ReactNode } from 'react'

import { LemonTag } from '@posthog/lemon-ui'

import type { OverrideSource } from 'lib/components/Cards/InsightCard/insightDetailsFilterOverrides'

export interface InsightFilterOverrideProps {
    source?: OverrideSource
    savedValue?: ReactNode
    children: ReactNode
}

export function InsightFilterOverride({ source, savedValue, children }: InsightFilterOverrideProps): JSX.Element {
    if (!source) {
        return <>{children}</>
    }

    return (
        <div className="flex flex-col items-start gap-1">
            <div className="flex flex-wrap items-center gap-1">
                {children}
                <LemonTag type="completion" size="small">
                    {source === 'tile' ? 'Tile' : 'Dashboard'}
                </LemonTag>
            </div>
            {savedValue && (
                <span className="text-xs text-muted-alt">
                    <span>Saved: </span>
                    <span className="line-through">{savedValue}</span>
                </span>
            )}
        </div>
    )
}
