import { IconArrowRight, IconBolt } from '@posthog/icons'

import { SignalSourceConfig } from '../../types'
import { getSourceProductMeta } from '../badges/sourceProductIcons'
import { sourceTriggerCopy } from './emptyStateCopy'

export function SignalSourceFlowRow({ source }: { source: SignalSourceConfig }): JSX.Element {
    const sourceMeta = getSourceProductMeta(source.source_product)
    const SourceIcon = sourceMeta?.Icon ?? IconBolt

    return (
        <div className="grid grid-cols-[2rem_minmax(0,1fr)] gap-3 border-b border-primary px-1 py-3 last:border-b-0">
            <div className="flex justify-center">
                <div className="relative flex size-8 shrink-0 items-center justify-center rounded-full border border-primary bg-bg-light">
                    <SourceIcon className={sourceMeta?.colorClass ?? 'text-secondary'} />
                    <span
                        className="absolute -right-0.5 -top-0.5 size-2.5 rounded-full border-2 border-bg-light bg-success motion-safe:animate-pulse"
                        aria-hidden
                    />
                </div>
            </div>
            <div className="min-w-0">
                <div className="truncate text-sm font-medium">{sourceMeta?.label ?? 'Signal source'}</div>
                <div className="mt-2 grid grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] items-center gap-3 text-xs">
                    <div className="min-w-0">
                        <div className="mb-0.5 text-[10px] font-medium text-secondary">When</div>
                        <div className="text-primary">{sourceTriggerCopy(source.source_type)}</div>
                    </div>
                    <div className="flex items-center text-tertiary" aria-hidden>
                        <span className="h-px w-4 bg-border-primary" />
                        <IconArrowRight className="-ml-0.5 shrink-0" />
                    </div>
                    <div className="min-w-0">
                        <div className="mb-0.5 text-[10px] font-medium text-secondary">Then</div>
                        <div className="text-tertiary">Investigate and open a pull request when fixable.</div>
                    </div>
                </div>
            </div>
        </div>
    )
}
