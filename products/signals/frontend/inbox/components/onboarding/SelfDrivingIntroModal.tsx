import { useEffect } from 'react'

import { LemonButton, LemonModal } from '@posthog/lemon-ui'

import { Logomark } from 'lib/brand'
import { urls } from 'scenes/urls'

import { captureSelfDrivingIntroModalViewed } from '../../inboxAnalytics'
import { LoopDiagram } from './LoopDiagram'

export interface SelfDrivingIntroModalProps {
    isOpen: boolean
    onClose: () => void
    /** Render the modal content without the portal/overlay, for Storybook snapshots. */
    inline?: boolean
}

/**
 * A short introduction to self-driving, shown before sending someone to the inbox: the same
 * headline, explainer, and animated loop diagram as the inbox welcome takeover, with the setup
 * details left to the inbox itself.
 */
export function SelfDrivingIntroModal({ isOpen, onClose, inline }: SelfDrivingIntroModalProps): JSX.Element {
    useEffect(() => {
        if (isOpen) {
            captureSelfDrivingIntroModalViewed()
        }
    }, [isOpen])

    return (
        <LemonModal
            isOpen={isOpen}
            onClose={onClose}
            width={880}
            inline={inline}
            footer={
                <>
                    <LemonButton type="secondary" onClick={onClose} data-attr="self-driving-intro-modal-dismiss">
                        Maybe later
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        to={urls.inbox()}
                        onClick={onClose}
                        data-attr="self-driving-intro-modal-open-inbox"
                    >
                        Open inbox
                    </LemonButton>
                </>
            }
        >
            <div className="flex flex-col items-center py-4 text-center">
                <div className="mb-5">
                    <Logomark size="xl" />
                </div>
                <h2 className="mb-3 text-2xl font-bold leading-[1.1] tracking-[-0.02em]">Ship fixes while you sleep</h2>
                <p className="mb-8 max-w-[560px] text-[15px] leading-[1.55] text-secondary">
                    PostHog watches your session replays, errors, and Slack. When it finds something worth fixing, it
                    writes the pull request. You review and merge.
                </p>
                <LoopDiagram />
                <p className="mt-6 text-xs text-tertiary">
                    Your first 3 PRs each month are free, then $15 per PR. Reports are always free.
                </p>
            </div>
        </LemonModal>
    )
}
