import { IconCopy } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { WavingHog } from 'lib/components/hedgehogs'
import { copyToClipboard } from 'lib/utils/copyToClipboard'

export function ReferralsAttributedSignupsIntro({
    referralShareUrl,
    copyDisabledReason,
}: {
    referralShareUrl: string | null
    copyDisabledReason: string | undefined
}): JSX.Element {
    return (
        <div
            data-attr="referrals-attributed-signups-empty"
            className="flex flex-col-reverse sm:flex-row items-center justify-center gap-6 w-full max-w-[40rem] mx-auto"
        >
            <div className="flex flex-col gap-3 flex-1 min-w-0 text-center sm:text-left">
                <p className="m-0 text-[17px] font-semibold text-default leading-snug text-balance">
                    Your fan club spreadsheet is peacefully empty
                </p>
                <p className="m-0 text-secondary text-[15px] leading-relaxed text-balance">
                    The moment someone waltzes into PostHog through your link, they&apos;ll flop into this tidy little
                    list with timestamps and onboarding progress sprinkled in for context. Until then, air out your link
                    somewhere fun and check back like someone peeking into a warmed-up oven.
                </p>
                <div className="flex flex-wrap gap-2 justify-center sm:justify-start pt-0.5">
                    <LemonButton
                        type="primary"
                        size="small"
                        icon={<IconCopy />}
                        disabledReason={copyDisabledReason}
                        data-attr="referrals-empty-copy-link"
                        onClick={() => {
                            if (referralShareUrl) {
                                void copyToClipboard(referralShareUrl, 'referral link')
                            }
                        }}
                    >
                        Copy signup link
                    </LemonButton>
                </div>
            </div>
            <div className="shrink-0" aria-hidden>
                <WavingHog alt="" draggable={false} className="w-32 sm:w-[8.75rem] h-auto drop-shadow-md" />
            </div>
        </div>
    )
}
