import { IconBell, IconThumbsDown, IconThumbsDownFilled, IconThumbsUp, IconThumbsUpFilled } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import type { AnomalySeriesApi } from 'products/signals/frontend/generated/api.schemas'

import type { AnomalyRowRating } from './anomaliesTabLogic'
import { newAlertPath } from './anomalyInsightLinks'

export interface AnomalyRowActionsProps {
    series: AnomalySeriesApi
    rating: AnomalyRowRating | undefined
    onRate: (rating: AnomalyRowRating) => void
    onCreateAlert: () => void
}

export function AnomalyRowActions({ series, rating, onRate, onCreateAlert }: AnomalyRowActionsProps): JSX.Element {
    const alertPath = newAlertPath(series.insight_url)
    return (
        <div className="flex flex-wrap items-center gap-1">
            {alertPath && (
                <LemonButton
                    type="secondary"
                    size="xsmall"
                    icon={<IconBell />}
                    to={alertPath}
                    onClick={onCreateAlert}
                    data-attr="anomalies-tab-create-alert"
                >
                    Create alert
                </LemonButton>
            )}
            <LemonButton
                type="tertiary"
                size="xsmall"
                icon={rating === 'useful' ? <IconThumbsUpFilled /> : <IconThumbsUp />}
                active={rating === 'useful'}
                tooltip={rating ? 'Thanks for the feedback' : 'Useful'}
                aria-label="Useful"
                aria-pressed={rating === 'useful'}
                onClick={() => onRate('useful')}
                data-attr="anomalies-tab-rate-useful"
            />
            <LemonButton
                type="tertiary"
                size="xsmall"
                icon={rating === 'not_useful' ? <IconThumbsDownFilled /> : <IconThumbsDown />}
                active={rating === 'not_useful'}
                tooltip={rating ? 'Thanks for the feedback' : 'Not useful'}
                aria-label="Not useful"
                aria-pressed={rating === 'not_useful'}
                onClick={() => onRate('not_useful')}
                data-attr="anomalies-tab-rate-not-useful"
            />
        </div>
    )
}
