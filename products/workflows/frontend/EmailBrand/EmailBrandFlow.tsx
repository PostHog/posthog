import { useActions, useValues } from 'kea'

import * as explorerPng from '@posthog/brand/hoggies/png/explorer'
import { LemonBanner, LemonButton, Spinner } from '@posthog/lemon-ui'

import { pngHoggie } from 'lib/brand/hoggies'
import { LemonProgress } from 'lib/lemon-ui/LemonProgress'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { emailBrandFlowLogic } from './emailBrandFlowLogic'
import type { EmailBrandFlowProps } from './emailBrandFlowLogic'
import { EmailBrandApp } from './steps/EmailBrandApp'
import { EmailBrandConnect } from './steps/EmailBrandConnect'
import { EmailBrandDetection } from './steps/EmailBrandDetection'
import { EmailBrandRepository } from './steps/EmailBrandRepository'
import { EmailBrandReview } from './steps/EmailBrandReview'

const HedgehogExplorer = pngHoggie(explorerPng)
const steps = ['Connect', 'Repository', 'Detect', 'Review']

export function EmailBrandFlow(props: EmailBrandFlowProps): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)
    return featureFlags['workflows-brand-detection'] ? <EmailBrandFlowContent {...props} /> : null
}

function EmailBrandFlowContent(props: EmailBrandFlowProps): JSX.Element {
    const logic = emailBrandFlowLogic(props)
    const { step, error, busy, initialLoading } = useValues(logic)
    const { skipToManual, retryInitial } = useActions(logic)
    const index =
        step === 'review' ? 3 : ['app', 'files', 'detecting'].includes(step) ? 2 : step === 'repository' ? 1 : 0
    return (
        <div className="@container min-w-0" data-attr="email-brand-flow">
            <ol className="flex flex-wrap gap-4 list-none p-0 mb-3 text-sm" aria-label="Email brand progress">
                {steps.map((label, position) => (
                    <li
                        key={label}
                        aria-current={position === index ? 'step' : undefined}
                        className={position === index ? 'font-semibold' : 'text-secondary'}
                    >{`${position + 1}. ${label}`}</li>
                ))}
            </ol>
            <LemonProgress percent={(index + 1) * 25} smoothing={false} />
            <HedgehogExplorer className="w-20 h-20 mx-auto mt-4" />
            {error && (
                <LemonBanner type="error" className="mt-4">
                    {error.code === 'github_disconnected'
                        ? 'PostHog lost access to GitHub. Connect GitHub again, then choose your repository.'
                        : error.code === 'github_busy'
                          ? 'GitHub is busy. Try again in a minute, or fill in your brand by hand.'
                          : error.code === 'repository_unreadable'
                            ? 'The PostHog GitHub App cannot read this repository. Grant it access on GitHub, then try again.'
                            : error.detail}
                </LemonBanner>
            )}
            {step === 'loading' ? (
                <div className="text-center py-8">
                    {initialLoading ? (
                        <Spinner />
                    ) : (
                        <LemonButton
                            type="primary"
                            onClick={retryInitial}
                            loading={busy}
                            data-attr="email-brand-retry-load"
                        >
                            Try again
                        </LemonButton>
                    )}
                </div>
            ) : step === 'connect' ? (
                <EmailBrandConnect {...props} />
            ) : step === 'repository' ? (
                <EmailBrandRepository {...props} />
            ) : step === 'app' ? (
                <EmailBrandApp {...props} />
            ) : step === 'review' ? (
                <EmailBrandReview {...props} />
            ) : (
                <EmailBrandDetection {...props} />
            )}
            <div className="flex flex-wrap justify-between gap-2 mt-4">
                {props.onCancel && (
                    <LemonButton type="tertiary" onClick={props.onCancel} data-attr="email-brand-cancel">
                        Cancel
                    </LemonButton>
                )}
                {step !== 'review' && (
                    <LemonButton
                        type="tertiary"
                        onClick={skipToManual}
                        disabledReason={initialLoading ? 'Wait for your brand to load' : undefined}
                        data-attr="email-brand-skip"
                    >
                        Skip, I'll fill it in by hand
                    </LemonButton>
                )}
            </div>
        </div>
    )
}
