import { IconChevronDown, IconCopy } from '@posthog/icons'
import { LemonMenu, LemonTag } from '@posthog/lemon-ui'

import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { parseCommaSeparatedSlackTargetDisplayLabels } from 'lib/utils/slackChannelValue'

import { TargetTypeEnumApi, type SubscriptionApi } from 'products/subscriptions/frontend/generated/api.schemas'

function parseEmailRecipients(targetValue: string): string[] {
    return targetValue
        .split(',')
        .map((e) => e.trim())
        .filter(Boolean)
}

function webhookHost(url: string): string {
    try {
        return new URL(url).host
    } catch {
        return 'Invalid URL'
    }
}

/**
 * A webhook URL is a credential, because anyone who has it can post to the channel. Show the host
 * only, and keep the full URL out of DOM attributes such as `title`.
 */
function WebhookDestinationCell({ url }: { url: string }): JSX.Element {
    const host = webhookHost(url)
    return (
        <span className="text-secondary max-w-md truncate block" title={host}>
            {host}
        </span>
    )
}

function DestinationListCell({ parts, copyDescription }: { parts: string[]; copyDescription: string }): JSX.Element {
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

export function SubscriptionDestinationCell({ sub }: { sub: SubscriptionApi }): JSX.Element {
    if (sub.target_type === TargetTypeEnumApi.Email) {
        const emails = parseEmailRecipients(sub.target_value)
        return <DestinationListCell parts={emails} copyDescription="email recipient" />
    }

    if (sub.target_type === TargetTypeEnumApi.Slack) {
        const parts = parseCommaSeparatedSlackTargetDisplayLabels(sub.target_value)
        return <DestinationListCell parts={parts} copyDescription="Slack destination" />
    }

    return <WebhookDestinationCell url={sub.target_value} />
}

/** Same destination UI as {@link SubscriptionDestinationCell}, for snapshot `target_type` / `target_value` (e.g. delivery history rows). */
export function SubscriptionDeliveryDestinationCell({
    targetType,
    targetValue,
}: {
    targetType: string
    targetValue: string
}): JSX.Element {
    const kind = targetType.toLowerCase()
    if (kind === TargetTypeEnumApi.Email) {
        return <DestinationListCell parts={parseEmailRecipients(targetValue)} copyDescription="email recipient" />
    }
    if (kind === TargetTypeEnumApi.Slack) {
        return (
            <DestinationListCell
                parts={parseCommaSeparatedSlackTargetDisplayLabels(targetValue)}
                copyDescription="Slack destination"
            />
        )
    }
    return <WebhookDestinationCell url={targetValue} />
}
