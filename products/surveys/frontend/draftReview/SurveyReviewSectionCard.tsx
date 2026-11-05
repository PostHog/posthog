import { useActions, useValues } from 'kea'
import { ReactNode } from 'react'

import { IconCheckCircle, IconPencil, IconWarning } from '@posthog/icons'
import { LemonBanner, LemonButton } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { cn } from 'lib/utils/css-classes'
import { surveyLogic } from 'scenes/surveys/surveyLogic'
import { surveysLogic } from 'scenes/surveys/surveysLogic'
import { canUseSurveyWizard } from 'scenes/surveys/utils'
import { urls } from 'scenes/urls'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

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
    const { survey } = useValues(surveyLogic)
    const { preferredEditor } = useValues(surveysLogic)
    const { editingSurvey, setSelectedSection } = useActions(surveyLogic)
    const editTarget =
        canUseSurveyWizard(survey) && preferredEditor === 'guided'
            ? { to: urls.surveyWizard(survey.id) }
            : {
                  onClick: () => {
                      setSelectedSection(section.editSection)
                      editingSurvey(true)
                  },
              }

    return (
        <section
            className={cn(
                'flex flex-col gap-2 rounded border bg-surface-primary p-4 motion-safe:transition-colors',
                highlighted && 'border-accent'
            )}
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
                <AccessControlAction
                    resourceType={AccessControlResourceType.Survey}
                    minAccessLevel={AccessControlLevel.Editor}
                    userAccessLevel={survey.user_access_level}
                >
                    <LemonButton
                        type="tertiary"
                        size="small"
                        icon={<IconPencil />}
                        {...editTarget}
                        data-attr={`survey-draft-review-edit-${section.key}`}
                    >
                        Edit
                    </LemonButton>
                </AccessControlAction>
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
