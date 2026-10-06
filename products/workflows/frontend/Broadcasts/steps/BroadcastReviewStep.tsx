import { useActions, useMountedLogic, useValues } from 'kea'

import { IconWarning } from '@posthog/icons'
import { LemonButton, Spinner } from '@posthog/lemon-ui'

import PropertyFiltersDisplay from 'lib/components/PropertyFilters/components/PropertyFiltersDisplay'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { humanFriendlyNumber } from 'lib/utils/numbers'

import { optOutCategoriesLogic } from '../../OptOuts/optOutCategoriesLogic'
import { BroadcastAudienceCohorts } from '../audience/BroadcastAudienceCohorts'
import { broadcastAudienceCohortsLogic } from '../audience/broadcastAudienceCohortsLogic'
import { BroadcastEmailPreview } from '../BroadcastEmailPreview'
import { BroadcastWizardStep, SENDERS_LOAD_FAILED_ERROR, broadcastWizardLogic } from '../broadcastWizardLogic'

function ReviewRow({
    label,
    step,
    showErrors = true,
    children,
}: {
    label: string
    step: Exclude<BroadcastWizardStep, 'review'>
    showErrors?: boolean
    children: React.ReactNode
}): JSX.Element {
    const { stepValidationErrors } = useValues(broadcastWizardLogic)
    const { setStep } = useActions(broadcastWizardLogic)
    const errors = showErrors ? stepValidationErrors[step] : []

    return (
        <div className="flex flex-col gap-1 border-b border-border pb-3 last:border-b-0">
            <div className="flex items-center justify-between gap-2">
                <span className="text-xs font-semibold uppercase tracking-wide text-muted">{label}</span>
                <LemonButton
                    size="xsmall"
                    type="secondary"
                    onClick={() => setStep(step)}
                    data-attr={`broadcast-review-edit-${step}`}
                >
                    Edit
                </LemonButton>
            </div>
            {errors.map((error) => (
                <LemonButton
                    key={error}
                    size="small"
                    status="danger"
                    icon={<IconWarning />}
                    onClick={() => setStep(step)}
                    data-attr={`broadcast-review-fix-${step}`}
                >
                    {error}
                </LemonButton>
            ))}
            <div>{children}</div>
        </div>
    )
}

export function BroadcastReviewStep(): JSX.Element {
    const {
        audienceProperties,
        blastRadius,
        blastRadiusLoading,
        goalEnabled,
        conversion,
        scheduleSummary,
        emailRateLimit,
        rateLimitedSendDuration,
        stepValidationErrors,
        emailSettings,
    } = useValues(broadcastWizardLogic)
    const { categories } = useValues(optOutCategoriesLogic())
    const category = categories.find((item) => item.id === emailSettings.messageCategoryId)
    const { props } = useMountedLogic(broadcastWizardLogic)
    const { nonCohortAudience } = useValues(broadcastAudienceCohortsLogic(props))
    const { integrationsLoading } = useValues(integrationsLogic)
    const { loadIntegrations } = useActions(integrationsLogic)

    // Errors a step owns show in that step's row, with a way to fix them.
    const stepErrors = new Set([
        ...stepValidationErrors.recipients,
        ...stepValidationErrors.goal,
        ...stepValidationErrors.content,
        ...stepValidationErrors.schedule,
    ])
    const reviewOnlyErrors = stepValidationErrors.review.filter((error) => !stepErrors.has(error))

    const goalEventNames: string[] = goalEnabled
        ? (conversion.events?.[0]?.filters?.events ?? []).map(
              (event: { name?: string; id?: string }) => event.name || String(event.id)
          )
        : []

    return (
        <div className="flex flex-col gap-4">
            <div>
                <h2 className="m-0 text-xl font-semibold">Review and confirm</h2>
                <p className="m-0 text-secondary">Check everything before sending. Emails can't be unsent.</p>
            </div>

            <div className="flex flex-col gap-3 rounded-lg border border-border bg-surface-primary p-4">
                <ReviewRow label="Recipients" step="recipients">
                    {blastRadiusLoading ? (
                        <Spinner />
                    ) : blastRadius ? (
                        <span>
                            Approximately {humanFriendlyNumber(blastRadius.affected)} of{' '}
                            {humanFriendlyNumber(blastRadius.total)} people
                        </span>
                    ) : (
                        <span className="text-warning">Couldn't estimate the audience size</span>
                    )}
                    {audienceProperties.length > 0 ? (
                        <div className="flex flex-col gap-2">
                            {nonCohortAudience.length > 0 ? (
                                <PropertyFiltersDisplay filters={nonCohortAudience} />
                            ) : null}
                            <BroadcastAudienceCohorts />
                        </div>
                    ) : (
                        <div className="text-muted text-xs">No filters. This broadcast goes to everyone.</div>
                    )}
                    {category && (
                        <div className="text-xs text-secondary">
                            Message category: {category.name}
                            {category.category_type === 'transactional'
                                ? '. Sent even to people who unsubscribed.'
                                : '. People who unsubscribed from it are skipped.'}
                        </div>
                    )}
                </ReviewRow>

                <ReviewRow label="Goal" step="goal">
                    {goalEnabled ? (
                        goalEventNames.length > 0 ? (
                            <span>Conversion when a person performs: {goalEventNames.join(', ')}</span>
                        ) : (
                            <span>Conversion goal based on property changes</span>
                        )
                    ) : (
                        <span className="text-muted">No goal</span>
                    )}
                </ReviewRow>

                <ReviewRow label="Email" step="content">
                    {!emailSettings.trackingEnabled && (
                        <div className="text-xs text-secondary">Open and click tracking is off.</div>
                    )}
                    {emailSettings.utmTagsEnabled && <div className="text-xs text-secondary">Links get UTM tags.</div>}
                    <BroadcastEmailPreview />
                </ReviewRow>

                <ReviewRow label="Schedule" step="schedule">
                    {scheduleSummary}
                </ReviewRow>

                {emailRateLimit && (
                    <ReviewRow label="Sending rate" step="schedule" showErrors={false}>
                        At most {humanFriendlyNumber(emailRateLimit.count)} emails per {emailRateLimit.period}
                        {rateLimitedSendDuration ? `, so about ${rateLimitedSendDuration} to reach everyone` : ''}
                    </ReviewRow>
                )}
            </div>

            {reviewOnlyErrors.length > 0 && (
                <div className="flex flex-col gap-1">
                    {reviewOnlyErrors.map((error) => (
                        <div key={error} className="text-danger text-xs">
                            {error}
                        </div>
                    ))}
                    {reviewOnlyErrors.includes(SENDERS_LOAD_FAILED_ERROR) && (
                        <div>
                            <LemonButton
                                type="secondary"
                                size="small"
                                onClick={() => loadIntegrations()}
                                loading={integrationsLoading}
                                data-attr="broadcast-reload-senders"
                            >
                                Reload email senders
                            </LemonButton>
                        </div>
                    )}
                </div>
            )}
        </div>
    )
}
