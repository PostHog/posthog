import { ReactNode } from 'react'

import { Logomark } from 'lib/brand'

import { InboxMcpBanner } from '../InboxMcpBanner'

interface InboxWelcomeLayoutProps {
    title: string
    description: string
    illustration: ReactNode
    footer: string
    children: ReactNode
}

export function InboxWelcomeLayout({
    title,
    description,
    illustration,
    footer,
    children,
}: InboxWelcomeLayoutProps): JSX.Element {
    return (
        <div className="InboxWelcome @container/welcome flex min-h-full flex-col justify-center py-10">
            <div className="mx-auto mb-8 w-full max-w-4xl px-6">
                <InboxMcpBanner />
            </div>
            <div className="px-6 pb-12">
                <div className="mx-auto flex max-w-[720px] flex-col items-center text-center">
                    <div className="mb-7">
                        <Logomark jumpOnClick size="xl" />
                    </div>
                    <h1 className="mb-4 text-2xl font-bold leading-[1.1] tracking-[-0.02em] @2xl/welcome:text-[32px]">
                        {title}
                    </h1>
                    <p className="mb-9 max-w-[560px] text-[15px] leading-[1.55] text-secondary">{description}</p>
                    {children}
                </div>
            </div>
            <div className="px-6 @3xl/welcome:px-12">
                <div className="mx-auto max-w-[1060px]">
                    {illustration}
                    <p className="mt-6 text-center text-xs text-tertiary">{footer}</p>
                </div>
            </div>
        </div>
    )
}
