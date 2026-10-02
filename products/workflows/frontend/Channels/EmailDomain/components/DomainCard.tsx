import clsx from 'clsx'

import { IconCheck } from '@posthog/icons'
import { LemonTag } from '@posthog/lemon-ui'

import { InferredDomain } from '../inferDomains'

export function DomainCard({
    domain,
    reasons,
    recommended,
    selected,
    onSelect,
}: InferredDomain & { selected: boolean; onSelect: () => void }): JSX.Element {
    return (
        <button
            type="button"
            onClick={onSelect}
            aria-pressed={selected}
            data-attr="email-domain-pick-domain"
            className={clsx(
                'w-full text-left rounded-lg border-2 p-4 flex items-start gap-3 transition-colors motion-reduce:transition-none cursor-pointer',
                selected ? 'border-accent bg-accent-highlight-secondary' : 'border-primary bg-surface-primary'
            )}
        >
            <span className="flex flex-col gap-1 min-w-0 flex-1">
                <span className="flex flex-wrap items-center gap-2">
                    <span className="font-mono text-lg @md:text-xl font-semibold break-all">{domain}</span>
                    {recommended && <LemonTag type="highlight">Recommended</LemonTag>}
                </span>
                {reasons.map((reason) => (
                    <span key={reason} className="text-xs text-secondary">
                        {reason}
                    </span>
                ))}
            </span>
            <span
                className={clsx(
                    'shrink-0 w-6 h-6 rounded-full border-2 inline-flex items-center justify-center',
                    selected ? 'bg-accent border-accent text-white' : 'border-primary'
                )}
            >
                {selected && <IconCheck />}
            </span>
        </button>
    )
}
