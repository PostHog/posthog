import { Field, FieldDescription, FieldLabel } from '@posthog/quill'

import { TagsCombobox } from 'lib/components/Scenes/TagsCombobox'

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
    return (
        <div className="flex max-w-160 flex-col gap-4">
            <Field>
                <FieldLabel>Blocked domains</FieldLabel>
                <TagsCombobox
                    value={blockedHosts}
                    onChange={onBlockedHostsChange}
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
                <FieldLabel>Blocked IP addresses</FieldLabel>
                <TagsCombobox
                    value={blockedIps}
                    onChange={onBlockedIpsChange}
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
