import { useId } from 'react'

import { Field, FieldDescription, FieldLabel } from '@posthog/quill'

import { TagsCombobox } from 'lib/components/Scenes/TagsCombobox'

import { splitRequestListEntries } from './splitRequestListEntries'

export function QuillFeatureFlagRequestAllowlist({
    allowedHosts,
    allowedIps,
    onAllowedHostsChange,
    onAllowedIpsChange,
    disabled,
    disabledReason,
}: {
    allowedHosts: string[]
    allowedIps: string[]
    onAllowedHostsChange: (hosts: string[]) => void
    onAllowedIpsChange: (ips: string[]) => void
    disabled: boolean
    disabledReason?: string | null
}): JSX.Element {
    const hostsId = useId()
    const ipsId = useId()

    return (
        <div className="flex max-w-160 flex-col gap-4">
            <Field>
                <FieldLabel htmlFor={hostsId}>Allowed domains</FieldLabel>
                <TagsCombobox
                    id={hostsId}
                    value={allowedHosts}
                    onChange={(hosts) => onAllowedHostsChange(splitRequestListEntries(hosts))}
                    customValueNoun="domain"
                    dataAttr="feature-flag-allowed-hosts-select"
                    placeholder="example.com"
                    disabled={disabled}
                    disabledReason={disabledReason}
                    className="w-full"
                />
                <FieldDescription>
                    Only pages on these domains get flags. Server-side and mobile SDKs aren't checked. Pages that hide
                    their domain, such as local files and sandboxed frames, get no flags. A domain also allows its
                    subdomains. Add up to 100 domains.
                </FieldDescription>
            </Field>
            <Field>
                <FieldLabel htmlFor={ipsId}>Allowed IP addresses</FieldLabel>
                <TagsCombobox
                    id={ipsId}
                    value={allowedIps}
                    onChange={(ips) => onAllowedIpsChange(splitRequestListEntries(ips))}
                    customValueNoun="IP address"
                    dataAttr="feature-flag-allowed-ips-select"
                    placeholder="203.0.113.7 or 198.51.100.0/24"
                    disabled={disabled}
                    disabledReason={disabledReason}
                    className="w-full"
                />
                <FieldDescription>
                    Only requests from these addresses get flags. This includes your servers and your users' browsers,
                    so leave it empty unless every caller has a fixed address. Enter up to 100 single addresses or CIDR
                    ranges.
                </FieldDescription>
            </Field>
        </div>
    )
}
