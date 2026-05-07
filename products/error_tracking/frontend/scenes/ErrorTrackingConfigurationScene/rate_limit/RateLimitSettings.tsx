import { useValues } from 'kea'
import { Form } from 'kea-forms'

import { LemonSelect } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'

import { IssueRateLimitSettings } from './IssueRateLimitSettings'
import { BUCKET_OPTIONS, rateLimitConfigLogic } from './rateLimitConfigLogic'
import { formatTotalDuration, RateLimitSimulationChart } from './RateLimitSimulationChart'

export function RateLimitSettings(): JSX.Element {
    const hasPerIssueRateLimit = useFeatureFlag('ERROR_TRACKING_RATE_LIMITING_PER_ISSUE')

    return (
        <div className="space-y-8">
            <ProjectRateLimitSection />
            {hasPerIssueRateLimit ? <IssueRateLimitSettings /> : null}
        </div>
    )
}

function ProjectRateLimitSection(): JSX.Element {
    const {
        configLoading,
        configFormChanged,
        isConfigFormSubmitting,
        configForm,
        volume,
        volumeLoading,
        volumeBucketMinutes,
    } = useValues(rateLimitConfigLogic)

    if (configLoading) {
        return (
            <div className="space-y-4">
                <LemonSkeleton className="w-full h-10" />
                <LemonSkeleton className="w-full h-64" />
            </div>
        )
    }

    return (
        <div className="space-y-4">
            <div>
                <h3 className="font-semibold text-base mb-1">Project-wide rate limit</h3>
                <p className="text-muted-foreground">
                    This limit applies across the entire project. Exceptions received above the configured rate are
                    dropped at ingestion.
                </p>
            </div>

            <Form logic={rateLimitConfigLogic} formKey="configForm" enableFormOnSubmit>
                <div className="grid grid-cols-1 md:grid-cols-10 gap-6">
                    <div className="md:col-span-3 space-y-3">
                        <LemonField name="project_rate_limit_value" label="Maximum exceptions">
                            {({ value, onChange }) => (
                                <LemonInput
                                    type="number"
                                    min={1}
                                    value={value ?? undefined}
                                    onChange={(v) => onChange(v ?? null)}
                                    placeholder="Unlimited"
                                    fullWidth
                                    data-attr="rate-limit-value"
                                />
                            )}
                        </LemonField>

                        <LemonField name="project_rate_limit_bucket_size_minutes" label="Per">
                            {({ value, onChange }) => (
                                <LemonSelect
                                    value={value}
                                    onChange={onChange}
                                    options={BUCKET_OPTIONS.map((o) => ({ label: o.label, value: o.minutes }))}
                                    fullWidth
                                    data-attr="rate-limit-bucket-size"
                                />
                            )}
                        </LemonField>

                        <p className="text-muted-foreground text-xs">
                            The maximum number of exceptions accepted per time window. Leave the value empty for no
                            limit.
                        </p>

                        <div className="flex justify-start pt-2">
                            <LemonButton
                                type="primary"
                                htmlType="submit"
                                disabledReason={!configFormChanged ? 'No changes to save' : undefined}
                                loading={isConfigFormSubmitting}
                            >
                                Save
                            </LemonButton>
                        </div>
                    </div>

                    <div className="md:col-span-7">
                        <div className="text-sm font-medium mb-1">
                            Exception volume — past {formatTotalDuration(volumeBucketMinutes)}
                        </div>
                        {volumeLoading ? (
                            <LemonSkeleton className="w-full h-80" />
                        ) : (
                            <RateLimitSimulationChart
                                volume={volume}
                                rateLimit={configForm.project_rate_limit_value}
                                bucketMinutes={volumeBucketMinutes}
                            />
                        )}
                    </div>
                </div>
            </Form>
        </div>
    )
}
