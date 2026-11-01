import clsx from 'clsx'

import { PAGE_HEALTH_STATUS_LABEL, PageHealthStatus, PageHealthSummary } from './pageHealth'
import { PageStatCard } from './PageStatCard'

const STATUS_DOT: Record<PageHealthStatus, string | null> = {
    loading: null,
    strong: 'bg-success',
    fair: 'bg-[var(--color-text-tertiary)]',
    needs_attention: 'bg-warning',
    not_found: 'bg-danger',
    no_data: null,
    not_set_up: null,
}

export interface PageHealthCardProps {
    card: PageHealthSummary
    onClick: () => void
    onHover: () => void
}

export function PageHealthCard({ card, onClick, onHover }: PageHealthCardProps): JSX.Element {
    const tooltip =
        card.reasons.length > 0 ? (
            <ul className="m-0 pl-4 flex flex-col gap-1">
                {card.reasons.map((reason) => (
                    <li key={reason}>{reason}</li>
                ))}
            </ul>
        ) : null

    return (
        <PageStatCard
            label={card.title}
            aside={
                <span className="inline-flex items-center gap-1.5 text-xs text-secondary whitespace-nowrap">
                    {STATUS_DOT[card.status] ? (
                        <span className={clsx('size-1.5 rounded-full', STATUS_DOT[card.status])} aria-hidden />
                    ) : null}
                    <span>{PAGE_HEALTH_STATUS_LABEL[card.status]}</span>
                </span>
            }
            value={card.value ?? <span className="text-secondary">-</span>}
            detail={card.value ? card.detail : card.headline}
            loading={card.status === 'loading'}
            tooltip={tooltip}
            onClick={onClick}
            onHover={onHover}
            data-attr={`page-report-health-card-${card.key}`}
        />
    )
}
