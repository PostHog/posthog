import { useId } from 'react'

import { Field, FieldDescription, FieldLabel } from '@posthog/quill'

import { TagsCombobox } from 'lib/components/Scenes/TagsCombobox'

import { splitRequestListEntries } from './splitRequestListEntries'

export function QuillFeatureFlagRequestBlocklist({
    blockedHosts,
    blockedIps,
    onBlockedHostsChange,
    onBlockedIpsChange,
    disabled,
    disabledReason,
}: {
    blockedHosts: string[]
    blockedIps: string[]
    onBlockedHostsChange: (hosts: string[]) => void
    onBlockedIpsChange: (ips: string[]) => void
    disabled: boolean
    disabledReason?: string | null
}): JSX.Element {
    const hostsId = useId()
    const ipsId = useId()

    return (
        <div className="flex max-w-160 flex-col gap-4">
            <Field>
                <FieldLabel htmlFor={hostsId}>Blocked domains</FieldLabel>
                <TagsCombobox
                    id={hostsId}
                    value={blockedHosts}
                    onChange={(hosts) => onBlockedHostsChange(splitRequestListEntries(hosts))}
                    customValueNoun="domain"
                    dataAttr="feature-flag-blocked-hosts-select"
                    placeholder="example.com"
                    disabled={disabled}
                    disabledReason={disabledReason}
                    className="w-full"
                />
                <FieldDescription>
                    Stops other websites that embed your project token from requesting flags. A domain also blocks its
                    subdomains. Add up to 100 domains.
                </FieldDescription>
            </Field>
            <Field>
                <FieldLabel htmlFor={ipsId}>Blocked IP addresses</FieldLabel>
                <TagsCombobox
                    id={ipsId}
                    value={blockedIps}
                    onChange={(ips) => onBlockedIpsChange(splitRequestListEntries(ips))}
                    customValueNoun="IP address"
                    dataAttr="feature-flag-blocked-ips-select"
                    placeholder="203.0.113.7 or 198.51.100.0/24"
                    disabled={disabled}
                    disabledReason={disabledReason}
                    className="w-full"
                />
                <FieldDescription>
                    Stops scripts that request flags from known addresses. Enter up to 100 single addresses or CIDR
                    ranges.
                </FieldDescription>
            </Field>
        </div>
    )
}
