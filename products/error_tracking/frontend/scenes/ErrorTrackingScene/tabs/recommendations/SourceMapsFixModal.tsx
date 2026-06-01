import { useActions, useValues } from 'kea'

import { IconCheckCircle, IconThumbsDown, IconThumbsUp } from '@posthog/icons'
import { LemonButton, LemonModal, LemonSegmentedButton, LemonTextArea } from '@posthog/lemon-ui'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { Popover } from 'lib/lemon-ui/Popover'
import { cn } from 'lib/utils/css-classes'

import { RATING_SCALE, sourceMapsFixWizardLogic } from './sourceMapsFixWizardLogic'

export function SourceMapsFixModal(): JSX.Element {
    const { isModalOpen, wizardCommand, feedbackRevealed, rating, ratingScore, feedbackText, feedbackSubmitted } =
        useValues(sourceMapsFixWizardLogic)
    const { closeModal, rateWizard, setRatingScore, setFeedbackText, submitFeedback, dismissFeedback } =
        useActions(sourceMapsFixWizardLogic)

    const positiveRating = ratingScore !== null && ratingScore > Math.ceil(RATING_SCALE / 2)

    return (
        <LemonModal isOpen={isModalOpen} onClose={closeModal} width={540} title="Let the wizard set up source maps">
            <div className="flex flex-col gap-4">
                <div className="flex items-start gap-3">
                    <p className="text-secondary mb-0">
                        The PostHog wizard detects your framework, wires up source map uploads, and verifies everything
                        works — so your stack traces become readable. Just run this in your project's root directory:
                    </p>
                </div>

                <CodeSnippet language={Language.Bash}>{wizardCommand}</CodeSnippet>

                <div
                    className={cn(
                        'grid transition-all duration-500 ease-out',
                        feedbackRevealed ? 'grid-rows-[1fr] opacity-100' : 'grid-rows-[0fr] opacity-0'
                    )}
                >
                    <div className="overflow-hidden">
                        <div className="flex items-center justify-between gap-2 border-t border-primary pt-3 mt-1">
                            <span className="font-medium">How did the wizard do?</span>
                            <Popover
                                visible={rating !== null}
                                onClickOutside={dismissFeedback}
                                placement="top-end"
                                overlay={
                                    <div className="flex flex-col gap-3 p-3 w-80">
                                        {feedbackSubmitted ? (
                                            <div className="flex items-center gap-2 py-1 font-medium text-success">
                                                <IconCheckCircle className="text-lg" />
                                                Thanks for the feedback!
                                            </div>
                                        ) : (
                                            <>
                                                <div className="flex flex-col gap-1">
                                                    <span className="font-medium">How did the wizard do?</span>
                                                    <LemonSegmentedButton
                                                        fullWidth
                                                        size="small"
                                                        value={ratingScore ?? undefined}
                                                        onChange={setRatingScore}
                                                        options={Array.from({ length: RATING_SCALE }, (_, i) => ({
                                                            value: i + 1,
                                                            label: String(i + 1),
                                                        }))}
                                                    />
                                                    <div className="flex justify-between text-xs text-muted">
                                                        <span>Very bad</span>
                                                        <span>Awesome</span>
                                                    </div>
                                                </div>
                                                <LemonTextArea
                                                    placeholder={
                                                        positiveRating
                                                            ? 'Nice! Anything that stood out? (optional)'
                                                            : 'Sorry about that — what went wrong? (optional)'
                                                    }
                                                    value={feedbackText}
                                                    onChange={setFeedbackText}
                                                    minRows={3}
                                                    autoFocus
                                                />
                                                <div className="flex justify-end">
                                                    <LemonButton type="primary" size="small" onClick={submitFeedback}>
                                                        Send
                                                    </LemonButton>
                                                </div>
                                            </>
                                        )}
                                    </div>
                                }
                            >
                                <div className="flex gap-1">
                                    <LemonButton
                                        icon={<IconThumbsUp />}
                                        type="secondary"
                                        size="small"
                                        active={rating === 'good'}
                                        onClick={() => rateWizard('good')}
                                        tooltip="It worked"
                                    />
                                    <LemonButton
                                        icon={<IconThumbsDown />}
                                        type="secondary"
                                        size="small"
                                        active={rating === 'bad'}
                                        onClick={() => rateWizard('bad')}
                                        tooltip="Didn't work"
                                    />
                                </div>
                            </Popover>
                        </div>
                    </div>
                </div>
            </div>
        </LemonModal>
    )
}
