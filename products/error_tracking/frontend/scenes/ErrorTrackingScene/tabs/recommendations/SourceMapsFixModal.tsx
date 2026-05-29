import { useActions, useValues } from 'kea'

import { IconCheckCircle, IconThumbsDown, IconThumbsUp } from '@posthog/icons'
import { LemonButton, LemonModal, LemonTextArea } from '@posthog/lemon-ui'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { Popover } from 'lib/lemon-ui/Popover'
import { cn } from 'lib/utils/css-classes'

import { sourceMapsFixWizardLogic } from './sourceMapsFixWizardLogic'

export function SourceMapsFixModal(): JSX.Element {
    const { isModalOpen, wizardCommand, feedbackRevealed, rating, feedbackText, feedbackSubmitted } =
        useValues(sourceMapsFixWizardLogic)
    const { closeModal, rateWizard, setFeedbackText, submitFeedback, dismissFeedback } =
        useActions(sourceMapsFixWizardLogic)

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
                                    <div className="flex flex-col gap-2 p-3 w-72">
                                        {feedbackSubmitted ? (
                                            <div className="flex items-center gap-2 py-1 font-medium text-success">
                                                <IconCheckCircle className="text-lg" />
                                                Thanks for the feedback!
                                            </div>
                                        ) : (
                                            <>
                                                <LemonTextArea
                                                    placeholder={
                                                        rating === 'good'
                                                            ? 'Nice! Anything that stood out? (optional)'
                                                            : 'Sorry about that — what went wrong? (optional)'
                                                    }
                                                    value={feedbackText}
                                                    onChange={setFeedbackText}
                                                    minRows={3}
                                                    autoFocus
                                                />
                                                <div className="flex justify-end gap-2">
                                                    <LemonButton size="small" onClick={dismissFeedback}>
                                                        Skip
                                                    </LemonButton>
                                                    <LemonButton
                                                        type="primary"
                                                        size="small"
                                                        onClick={submitFeedback}
                                                        disabledReason={
                                                            feedbackText.trim() ? undefined : 'Write a note first'
                                                        }
                                                    >
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
