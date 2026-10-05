import { useActions, useValues } from 'kea'

import { LemonButton, LemonCard, LemonModal, LemonSkeleton, LemonTag } from '@posthog/lemon-ui'

import { emailBrandEntryLogic } from './emailBrandEntryLogic'
import type { EmailBrandEntryProps } from './emailBrandEntryLogic'
import { EmailBrandFlow } from './EmailBrandFlow'

export function EmailBrandEntryPoint({ entryPoint }: EmailBrandEntryProps): JSX.Element | null {
    const logic = emailBrandEntryLogic({ entryPoint })
    const { enabled, isOpen, summary, summaryLoading } = useValues(logic)
    const { openFlow, closeFlow, complete } = useActions(logic)
    if (!enabled) {
        return null
    }
    return (
        <>
            <LemonCard hoverEffect={false} className="mb-4" data-attr={`email-brand-entry-${entryPoint}`}>
                <div className="flex flex-wrap items-start justify-between gap-4">
                    <div className="min-w-0 flex-1">
                        <h3>{entryPoint === 'channels' ? 'Email brand' : 'Create from your brand'}</h3>
                        {summaryLoading ? (
                            <LemonSkeleton className="h-5 w-40" />
                        ) : summary && entryPoint === 'channels' ? (
                            <div className="flex flex-wrap items-center gap-2">
                                <span className="min-w-0 max-w-full break-all">
                                    {summary.name || 'Your Email brand'}
                                </span>
                                <LemonTag>
                                    {summary.source_repository ? 'Detected from GitHub' : 'Entered by hand'}
                                </LemonTag>
                            </div>
                        ) : (
                            <p className="mb-0 text-secondary">
                                Use your logo, colors and font to start an email template. Detect them from GitHub or
                                fill them in by hand.
                            </p>
                        )}
                    </div>
                    <LemonButton type="primary" onClick={openFlow} data-attr="email-brand-open">
                        {entryPoint === 'channels'
                            ? summary
                                ? 'Edit Email brand'
                                : 'Set up Email brand'
                            : 'Create from your brand'}
                    </LemonButton>
                </div>
            </LemonCard>
            <LemonModal isOpen={isOpen} onClose={closeFlow} title="Email brand" width={1100}>
                {isOpen && (
                    <EmailBrandFlow
                        entryPoint={entryPoint}
                        onCancel={closeFlow}
                        onComplete={({ emailBrand, templateId }) => complete(emailBrand, templateId)}
                    />
                )}
            </LemonModal>
        </>
    )
}
