import { useValues } from 'kea'

import { IconExternal } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { emailDomainAutoConfigureLogic } from '../emailDomainAutoConfigureLogic'

export function DnsHostLink({ primary }: { primary?: boolean }): JSX.Element | null {
    const { dnsHost } = useValues(emailDomainAutoConfigureLogic)
    if (!dnsHost) {
        return null
    }
    return (
        <LemonButton
            type={primary ? 'primary' : 'tertiary'}
            size={primary ? 'large' : undefined}
            fullWidth={primary}
            center={primary}
            to={dnsHost.dns_settings_url}
            targetBlank
            sideIcon={<IconExternal />}
            data-attr="email-domain-open-dns-host"
        >
            Open {dnsHost.name}
        </LemonButton>
    )
}
