import { IconArrowLeft, IconArrowRight } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonCard } from 'lib/lemon-ui/LemonCard'

import type { Verdict } from './founderValidationLogic'

type Recommendation = 'refine' | 'decide' | 'continue'

// Low confidence means the LLM didn't have enough to evaluate — the right response is to
// give it more detail, not to charge forward, regardless of score. Below that, a low score
// is the next-strongest signal to refine. Strong + confident is the only path we green-light.
function recommend(verdict: Verdict): Recommendation {
    if (verdict.confidence === 'low') {
        return 'refine'
    }
    if (verdict.score < 5) {
        return 'refine'
    }
    if (verdict.score >= 8 && verdict.confidence === 'high') {
        return 'continue'
    }
    return 'decide'
}

interface Copy {
    cardClass: string
    heading: string
    body: string
    primary: { label: string; onClick: () => void; icon: JSX.Element }
    secondary: { label: string; onClick: () => void; icon: JSX.Element }
}

export function ValidationNextStep({
    verdict,
    onRefine,
    onContinue,
}: {
    verdict: Verdict
    onRefine: () => void
    onContinue: () => void
}): JSX.Element {
    const recommendation = recommend(verdict)
    const copy = COPY[recommendation]({ onRefine, onContinue })

    return (
        <LemonCard className={`p-6 ${copy.cardClass}`}>
            <h3 className="text-base font-semibold">{copy.heading}</h3>
            <p className="text-sm text-text-secondary mt-1">{copy.body}</p>
            <div className="flex gap-2 mt-4">
                <LemonButton type="primary" icon={copy.primary.icon} onClick={copy.primary.onClick}>
                    {copy.primary.label}
                </LemonButton>
                <LemonButton type="secondary" icon={copy.secondary.icon} onClick={copy.secondary.onClick}>
                    {copy.secondary.label}
                </LemonButton>
            </div>
        </LemonCard>
    )
}

const COPY: Record<Recommendation, (cbs: { onRefine: () => void; onContinue: () => void }) => Copy> = {
    refine: ({ onRefine, onContinue }) => ({
        cardClass: 'border-l-4 border-l-danger',
        heading: 'Refine your ideation before going further',
        body: 'The validation surfaced critical weaknesses or the LLM had too little to evaluate. Strengthen the riskiest assumptions in stage 1 before committing time to go-to-market.',
        primary: {
            label: 'Back to ideation',
            onClick: onRefine,
            icon: <IconArrowLeft />,
        },
        secondary: {
            label: 'Continue anyway',
            onClick: onContinue,
            icon: <IconArrowRight />,
        },
    }),
    decide: ({ onRefine, onContinue }) => ({
        cardClass: 'border-l-4 border-l-warning',
        heading: 'Mixed signal — your call',
        body: 'The idea has real merit but also real risk. Review the assumptions and experiments above, then decide whether to sharpen the ideation or proceed to GTM.',
        primary: {
            label: 'Continue to GTM',
            onClick: onContinue,
            icon: <IconArrowRight />,
        },
        secondary: {
            label: 'Refine ideation',
            onClick: onRefine,
            icon: <IconArrowLeft />,
        },
    }),
    continue: ({ onRefine, onContinue }) => ({
        cardClass: 'border-l-4 border-l-success',
        heading: "This idea looks strong — let's plan how to bring it to market",
        body: 'High score with high confidence. Address the experiments above as part of GTM execution rather than gating on them.',
        primary: {
            label: 'Continue to GTM',
            onClick: onContinue,
            icon: <IconArrowRight />,
        },
        secondary: {
            label: 'Refine ideation',
            onClick: onRefine,
            icon: <IconArrowLeft />,
        },
    }),
}
