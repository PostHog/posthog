import { ReactNode } from 'react'

import { IconCheckCircle, IconWarning } from '@posthog/icons'
import { LemonBanner } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'

import { SurveyReviewSection } from './surveyReview'

interface SurveyReviewSectionCardProps {
    section: SurveyReviewSection
    highlighted: boolean
    onHighlightChange: (highlighted: boolean) => void
    children?: ReactNode
}

export function SurveyReviewSectionCard({
    section,
    highlighted,
    onHighlightChange,
    children,
}: SurveyReviewSectionCardProps): JSX.Element {
    return (
        <section
            className={cn(
                'flex flex-col gap-2 rounded border bg-surface-primary p-4 motion-safe:transition-colors',
                highlighted && 'border-accent'
            )}
            data-attr={`survey-draft-review-section-${section.key}`}
            onMouseEnter={() => onHighlightChange(true)}
            onMouseLeave={() => onHighlightChange(false)}
            onFocus={() => onHighlightChange(true)}
            onBlur={() => onHighlightChange(false)}
        >
            <div className="flex items-center gap-2">
                {section.status === 'ready' ? (
                    <IconCheckCircle className="size-5 shrink-0 text-success" aria-label="Ready" />
                ) : (
                    <IconWarning className="size-5 shrink-0 text-warning" aria-label="Needs a look" />
                )}
                <h3 className="m-0 flex-1 text-sm font-semibold">{section.title}</h3>
            </div>
            <p className="m-0 text-sm">
                {section.summary.map((part, index) =>
                    typeof part === 'string' ? (
                        <span key={index}>{part}</span>
                    ) : (
                        <strong key={index}>{part.emphasis}</strong>
                    )
                )}
            </p>
            {children}
            {section.warning && <LemonBanner type="warning">{section.warning}</LemonBanner>}
        </section>
    )
}
