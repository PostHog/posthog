// PROTOTYPE (branch prototype/sending-limits-ux): a stand-in for the domain setup ReadyStep, never merge.
import clsx from 'clsx'
import { ReactNode } from 'react'

import { IconCheck } from '@posthog/icons'
import { LemonButton, LemonCollapse, LemonInput } from '@posthog/lemon-ui'

import { StepHeading } from '../Channels/EmailDomain/components/StepHeading'
import { HedgehogPanic, HedgehogRocket } from '../Channels/EmailDomain/hoggies'

interface SetupShellProps {
    domain: string
    tone?: 'success' | 'warning'
    title?: ReactNode
    lead?: ReactNode
    children?: ReactNode
}

export function SetupShell({ domain, tone = 'success', title, lead, children }: SetupShellProps): JSX.Element {
    return (
        <div className="@container flex flex-col gap-8 max-w-200 mx-auto">
            <div
                className={clsx(
                    'rounded-xl border p-6 @md:p-8',
                    tone === 'success' ? 'border-success bg-success-highlight' : 'border-warning bg-warning-highlight'
                )}
            >
                <StepHeading
                    Hoggie={tone === 'success' ? HedgehogRocket : HedgehogPanic}
                    title={title ?? <>You can send from {domain}</>}
                    lead={lead ?? 'All 3 settings are in place. Inboxes now know these emails really come from you.'}
                />
            </div>
            {children}
            <div className="border rounded p-4 flex flex-col gap-3 opacity-70">
                <span className="text-xs text-secondary">Unchanged from today</span>
                <div className="flex flex-col gap-1">
                    <label className="text-sm">Name</label>
                    <LemonInput value="Hedgebox" onChange={() => {}} />
                </div>
                <div className="text-sm">
                    Sends as <strong>hello@{domain}</strong>
                </div>
                <div>
                    <LemonButton type="secondary">Send me a test email</LemonButton>
                </div>
            </div>
            <LemonCollapse
                className="opacity-70"
                panels={[
                    {
                        key: 'records',
                        header: (
                            <span className="flex items-center gap-2">
                                <IconCheck className="text-success" />
                                <span>3 settings in place at your DNS host</span>
                            </span>
                        ),
                        content: <span className="text-secondary">DKIM, SPF and DMARC records.</span>,
                    },
                    {
                        key: 'tips',
                        header: <span>Keep your emails out of spam</span>,
                        content: (
                            <span className="text-secondary">
                                Today's sending tips: start small, only email people who asked, make it easy to
                                unsubscribe.
                            </span>
                        ),
                    },
                ]}
            />
        </div>
    )
}
