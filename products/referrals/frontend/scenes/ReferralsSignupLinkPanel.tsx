import { IconCopy } from '@posthog/icons'
import { LemonButton, LemonCard, Spinner } from '@posthog/lemon-ui'

import { copyToClipboard } from 'lib/utils/copyToClipboard'

export function ReferralsSignupLinkPanel({
    referralShareUrl,
    copyDisabledReason,
}: {
    referralShareUrl: string | null
    copyDisabledReason: string | undefined
}): JSX.Element {
    return (
        <LemonCard hoverEffect={false} className="mb-10 overflow-hidden shadow-sm border-primary p-0">
            <div className="relative">
                <div
                    aria-hidden
                    className="absolute inset-y-0 left-0 w-1 rounded-l bg-gradient-to-b from-accent-active to-accent"
                />
                <div className="pl-6 pr-6 py-6 flex flex-col gap-5">
                    <div className="flex gap-4 min-w-0">
                        <div className="hidden sm:flex shrink-0 size-11 rounded-xl items-center justify-center bg-accent-highlight-secondary border border-accent/25">
                            <IconCopy className="text-accent text-xl" />
                        </div>
                        <div className="min-w-0 flex-1">
                            <p className="m-0 text-lg font-semibold text-default tracking-tight">Your signup link</p>
                            <p className="m-0 mt-1 text-secondary text-[15px] leading-snug max-w-2xl">
                                Drop this wherever you yak about analytics: your team chat, timeline, sleepy newsletter
                                footer, whichever. Anyone who swings by and joins shows up below as yours ✨
                            </p>
                        </div>
                    </div>

                    {!referralShareUrl ? (
                        <div className="flex items-center gap-2 text-secondary text-sm">
                            <Spinner />
                            Preparing your link…
                        </div>
                    ) : (
                        <div className="flex flex-col sm:flex-row gap-3 sm:items-center w-full max-w-2xl">
                            <div
                                data-attr="social-referral-link"
                                className="min-w-0 flex-1 rounded-lg border border-primary bg-fill-secondary px-3.5 py-3 shadow-[inset_0_1px_0_rgba(0,0,0,0.04)] dark:shadow-none"
                            >
                                <span className="block font-mono text-[13px] text-default truncate select-all cursor-default">
                                    {referralShareUrl}
                                </span>
                            </div>
                            <LemonButton
                                type="primary"
                                size="small"
                                className="shrink-0"
                                icon={<IconCopy />}
                                disabledReason={copyDisabledReason}
                                data-attr="social-referral-copy"
                                onClick={() => {
                                    if (referralShareUrl) {
                                        void copyToClipboard(referralShareUrl, 'referral link')
                                    }
                                }}
                            >
                                Copy link
                            </LemonButton>
                        </div>
                    )}
                </div>
            </div>
        </LemonCard>
    )
}
