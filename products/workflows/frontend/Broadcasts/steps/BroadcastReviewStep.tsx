import { useValues } from 'kea'

import { Spinner } from '@posthog/lemon-ui'

import PropertyFiltersDisplay from 'lib/components/PropertyFilters/components/PropertyFiltersDisplay'
import { humanFriendlyNumber } from 'lib/utils/numbers'

import { broadcastWizardLogic } from '../broadcastWizardLogic'

function ReviewRow({ label, children }: { label: string; children: React.ReactNode }): JSX.Element {
    return (
        <div className="flex flex-col gap-1 border-b border-border pb-3 last:border-b-0">
            <span className="text-xs font-semibold uppercase tracking-wide text-muted">{label}</span>
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
        email,
        scheduleSummary,
        emailRateLimit,
        rateLimitedSendDuration,
        stepValidationErrors,
    } = useValues(broadcastWizardLogic)

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
                <ReviewRow label="Recipients">
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
                        <PropertyFiltersDisplay filters={audienceProperties} />
                    ) : (
                        <div className="text-muted text-xs">No filters. This broadcast goes to everyone.</div>
                    )}
                </ReviewRow>

                <ReviewRow label="Goal">
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

                <ReviewRow label="Email">
                    <div className="flex flex-col gap-1">
                        <span className="font-semibold">{email.subject || 'No subject'}</span>
                        {email.html ? (
                            <iframe
                                srcDoc={email.html}
                                sandbox=""
                                title="Email preview"
                                className="h-64 w-full rounded border border-border"
                            />
                        ) : email.text ? (
                            <div className="text-muted whitespace-pre-wrap text-sm max-h-64 overflow-y-auto">
                                {email.text}
                            </div>
                        ) : (
                            <span className="text-muted">No content yet</span>
                        )}
                    </div>
                </ReviewRow>

                <ReviewRow label="Schedule">{scheduleSummary}</ReviewRow>

                {emailRateLimit && (
                    <ReviewRow label="Sending rate">
                        At most {humanFriendlyNumber(emailRateLimit.count)} emails per {emailRateLimit.period}
                        {rateLimitedSendDuration ? `, so about ${rateLimitedSendDuration} to reach everyone` : ''}
                    </ReviewRow>
                )}
            </div>

            {stepValidationErrors.review.length > 0 && (
                <div className="flex flex-col gap-1">
                    {stepValidationErrors.review.map((error) => (
                        <div key={error} className="text-danger text-xs">
                            {error}
                        </div>
                    ))}
                </div>
            )}
        </div>
    )
}
