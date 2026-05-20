import { useValues } from 'kea'

import { Link } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { EvaluationConfig, llmProviderKeysLogic } from './llmProviderKeysLogic'

export function TrialUsageMeter({
    showSettingsLink = false,
    noun = 'evaluations',
}: {
    showSettingsLink?: boolean
    noun?: string
}): JSX.Element | null {
    const { evaluationConfig } = useValues(llmProviderKeysLogic)

    if (!evaluationConfig || evaluationConfig.active_provider_key) {
        return null
    }

    return (
        <TrialUsageMeterDisplay evaluationConfig={evaluationConfig} showSettingsLink={showSettingsLink} noun={noun} />
    )
}

export function TrialUsageMeterDisplay({
    evaluationConfig,
    showSettingsLink = false,
    noun = 'evaluations',
}: {
    evaluationConfig: EvaluationConfig
    showSettingsLink?: boolean
    noun?: string
}): JSX.Element {
    const { trial_eval_limit, trial_evals_remaining } = evaluationConfig
    const percentUsed = Math.min(((trial_eval_limit - trial_evals_remaining) / trial_eval_limit) * 100, 100)
    const isExhausted = trial_evals_remaining <= 0

    return (
        <div className="rounded-lg p-4 space-y-3 border">
            <div className="flex justify-between items-center">
                <span className="font-medium">Trial {noun}</span>
                <span className={`text-sm ${isExhausted ? 'font-medium' : 'text-muted'}`}>
                    {trial_evals_remaining} of {trial_eval_limit} remaining
                </span>
            </div>
            <div className="h-2 bg-border rounded-full overflow-hidden">
                <div
                    className={`h-full transition-all ${isExhausted ? 'bg-danger' : 'bg-success'}`}
                    // eslint-disable-next-line react/forbid-dom-props
                    style={{ width: `${percentUsed}%` }}
                />
            </div>
            {isExhausted ? (
                <p className="text-sm">
                    Trial {noun} exhausted.{' '}
                    {showSettingsLink ? (
                        <Link to={urls.settings('environment-llm-analytics', 'llm-analytics-byok')}>
                            Add your API key
                        </Link>
                    ) : (
                        'Add your API key'
                    )}{' '}
                    to continue.
                </p>
            ) : (
                <p className="text-sm text-muted">
                    You have {trial_evals_remaining} {noun} to try things out before{' '}
                    {showSettingsLink ? (
                        <Link to={urls.settings('environment-llm-analytics', 'llm-analytics-byok')}>
                            adding your own key
                        </Link>
                    ) : (
                        'adding your own key'
                    )}
                    .
                </p>
            )}
        </div>
    )
}
