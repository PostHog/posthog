import { useActions, useValues } from 'kea'
import { useRef, useState } from 'react'

import { IconCheckCircle, IconCopy, IconTerminal, IconThumbsDown, IconThumbsUp } from '@posthog/icons'
import { LemonButton, LemonDivider, LemonModal, LemonSegmentedButton, LemonTextArea } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { Popover } from 'lib/lemon-ui/Popover'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { cn } from 'lib/utils/css-classes'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'

import { CloudSetupLauncher, CloudSetupPreload, SourceMapsCloudSetup } from './SourceMapsCloudSetup'
import { sourceMapsCloudSetupLogic } from './sourceMapsCloudSetupLogic'
import { RATING_SCALE, sourceMapsFixWizardLogic } from './sourceMapsFixWizardLogic'
import { WizardHog } from './sourceMapsWizardVisuals'

export function SourceMapsFixModal(): JSX.Element {
    const { isModalOpen } = useValues(sourceMapsFixWizardLogic)
    const { closeModal } = useActions(sourceMapsFixWizardLogic)
    const { isCloudOrDev } = useValues(preflightLogic)
    const canScanRepository = useFeatureFlag('ERROR_TRACKING_REPOSITORY_DETECTION') && !!isCloudOrDev
    const [castKey, setCastKey] = useState(0)

    return (
        <>
            {canScanRepository && <CloudSetupPreload />}
            <LemonModal isOpen={isModalOpen} onClose={closeModal} width={540} simple>
                <div className="relative">
                    {canScanRepository ? (
                        <CloudSetupModalContent castKey={castKey} onCopy={setCastKey} />
                    ) : (
                        <>
                            <WizardHero castKey={castKey} title="Readable stack traces in one command" />
                            <div className="flex flex-col gap-3 px-6 pb-6 pt-2">
                                <ManualCommandSection onCopy={setCastKey} />
                                <WizardFeedbackSection />
                            </div>
                        </>
                    )}
                </div>
            </LemonModal>
        </>
    )
}

// Mounts the cloud setup logic, so it only lives (and polls) while the flag is on and the
// modal is open.
function CloudSetupModalContent({ castKey, onCopy }: { castKey: number; onCopy: (key: number) => void }): JSX.Element {
    const { step } = useValues(sourceMapsCloudSetupLogic)

    return (
        <>
            <WizardHero castKey={castKey} title="Readable stack traces in a few clicks" minimal={step !== 'intro'} />
            {step === 'intro' ? (
                <div className="flex flex-col gap-3 px-6 pb-6 pt-2">
                    <CloudSetupLauncher />
                    <OrDivider />
                    <ManualCommandSection onCopy={onCopy} />
                    <WizardFeedbackSection />
                </div>
            ) : (
                <SourceMapsCloudSetup />
            )}
        </>
    )
}

function WizardHero({
    castKey,
    title,
    minimal = false,
}: {
    castKey: number
    title: string
    minimal?: boolean
}): JSX.Element {
    return (
        <div className="flex flex-col items-center gap-2 px-6 pt-8 pb-6 text-center bg-[radial-gradient(ellipse_at_top_left,rgba(43,111,244,0.18),transparent_55%),radial-gradient(ellipse_at_bottom_right,rgba(255,101,31,0.16),transparent_55%)]">
            <WizardHog castKey={castKey} className="w-24 h-24" />
            {!minimal && (
                <>
                    <h3 className="text-xl font-bold mb-0">{title}</h3>
                    <p className="text-secondary text-sm mb-0 max-w-sm">
                        The wizard detects your framework, sets up automatic source map uploads in your project, and
                        verifies everything works.
                    </p>
                </>
            )}
        </div>
    )
}

function OrDivider(): JSX.Element {
    return (
        <div className="flex items-center gap-3">
            <LemonDivider className="flex-1 my-0" />
            <span className="text-xs text-muted">or</span>
            <LemonDivider className="flex-1 my-0" />
        </div>
    )
}

function ManualCommandSection({ onCopy }: { onCopy: (key: number) => void }): JSX.Element {
    return (
        <>
            <div className="flex justify-center">
                <WizardCommand onCopy={onCopy} />
            </div>
            <p className="text-xs text-muted text-center mb-0">Run it in your project's root directory</p>
        </>
    )
}

// Local command renderer instead of CommandBlock: same rainbow text, but no
// scale bounce or color flash on click, and a theme-aware hairline border.
function WizardCommand({ onCopy }: { onCopy: (key: number) => void }): JSX.Element {
    const { wizardCommand } = useValues(sourceMapsFixWizardLogic)
    const copyCount = useRef(0)

    const handleCopy = (): void => {
        void copyToClipboard(wizardCommand, 'Wizard command')
        copyCount.current += 1
        onCopy(copyCount.current)
    }

    return (
        <button
            type="button"
            onClick={handleCopy}
            aria-label="Copy wizard command"
            className="group inline-flex items-center gap-2 px-4 py-3 font-mono text-sm cursor-pointer max-w-full transition-colors rounded-lg bg-surface-primary border border-primary hover:border-blue-500"
        >
            <IconTerminal className="size-4 text-muted" />
            <code className="rainbow-text rainbow-text-animating !bg-transparent !p-0 !border-0 select-all min-w-0">
                {wizardCommand}
            </code>
            <IconCopy className="size-4 text-muted group-hover:text-primary" />
        </button>
    )
}

function WizardFeedbackSection(): JSX.Element {
    const { feedbackRevealed, rating, ratingScore, feedbackText, feedbackSubmitted } =
        useValues(sourceMapsFixWizardLogic)
    const { rateWizard, setRatingScore, setFeedbackText, submitFeedback, dismissFeedback } =
        useActions(sourceMapsFixWizardLogic)

    const positiveRating = ratingScore !== null && ratingScore > Math.ceil(RATING_SCALE / 2)

    return (
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
    )
}
