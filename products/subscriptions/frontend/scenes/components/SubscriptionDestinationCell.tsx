import { IconChevronDown, IconCopy } from '@posthog/icons'
import { LemonMenu, LemonTag } from '@posthog/lemon-ui'

import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { copyToClipboard } from 'lib/utils/copyToClipboard'

import type { SubscriptionDestination } from './subscriptionDestination'

export function SubscriptionDestinationCell({ destination }: { destination: SubscriptionDestination }): JSX.Element {
    const { parts, copyDescription } = destination

    if (copyDescription === null) {
        return (
            <span className="text-secondary max-w-md truncate block" title={parts[0]}>
                {parts[0]}
            </span>
        )
    }

    if (parts.length === 0) {
        return <span className="text-secondary">—</span>
    }

    if (parts.length === 1) {
        return (
            <span className="text-secondary max-w-xl truncate block" title={parts[0]}>
                <CopyToClipboardInline
                    tooltipMessage={null}
                    description={copyDescription}
                    style={{ justifyContent: 'flex-end' }}
                >
                    {parts[0]}
                </CopyToClipboardInline>
            </span>
        )
    }

    return (
        <span className="text-secondary inline-flex items-center gap-x-1 min-w-0 max-w-xl flex-wrap">
            <span className="min-w-0 truncate" title={parts[0]} data-attr="subscription-destination-primary">
                <CopyToClipboardInline
                    tooltipMessage={null}
                    description={copyDescription}
                    style={{ justifyContent: 'flex-end' }}
                >
                    {parts[0]}
                </CopyToClipboardInline>
            </span>
            <LemonMenu
                placement="bottom-start"
                items={parts.slice(1).map((part) => ({
                    label: part,
                    sideIcon: <IconCopy className="text-primary-3000" />,
                    onClick: () => copyToClipboard(part, copyDescription),
                }))}
            >
                <LemonTag type="primary" className="inline-flex">
                    <span>+{parts.length - 1}</span>
                    <IconChevronDown className="w-4 h-4" />
                </LemonTag>
            </LemonMenu>
        </span>
    )
}
