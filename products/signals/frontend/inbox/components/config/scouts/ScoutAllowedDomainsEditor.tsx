import { useState } from 'react'

import { LemonInput, LemonTag } from '@posthog/lemon-ui'

import type {
    PatchedSignalScoutConfigUpdateApi as SignalScoutConfigUpdate,
    SignalScoutConfigApi as SignalScoutConfig,
} from 'products/signals/frontend/generated/api.schemas'
import { SignalScoutConfigNetworkAccessEnumApi } from 'products/signals/frontend/generated/api.schemas'

import {
    MAX_SCOUT_ALLOWED_DOMAINS,
    parseScoutAllowedDomainsInput,
    scoutAllowedDomains,
    withScoutDomainRemoved,
    withScoutDomainsAdded,
} from '../../../utils/scoutAllowedDomains'

/**
 * The domain list a scout on custom network access may reach, on top of the trusted defaults.
 *
 * The API rejects custom mode with an empty list, so this editor owns both sides of that pair: the
 * first domain carries the mode switch with it, and the last domain cannot be removed while the
 * scout is still on custom.
 */
export function ScoutAllowedDomainsEditor({
    config,
    onUpdate,
    updating = false,
}: {
    config: SignalScoutConfig
    onUpdate: (configId: string, updates: SignalScoutConfigUpdate) => void
    updating?: boolean
}): JSX.Element {
    const [draft, setDraft] = useState('')
    const [error, setError] = useState<string | null>(null)
    const domains = scoutAllowedDomains(config)
    const isCustom = config.network_access === SignalScoutConfigNetworkAccessEnumApi.Custom
    const atCap = domains.length >= MAX_SCOUT_ALLOWED_DOMAINS

    const commitDraft = (): void => {
        const parsed = parseScoutAllowedDomainsInput(draft)
        if (parsed.invalid.length > 0) {
            setError(
                `${parsed.invalid.join(', ')} is not a domain name. Enter names like example.com or *.example.com, with no scheme, path, or port.`
            )
            return
        }
        const added = withScoutDomainsAdded(domains, parsed.domains)
        if (added.overCap) {
            setError(`A scout can reach up to ${MAX_SCOUT_ALLOWED_DOMAINS} custom domains.`)
            return
        }
        setError(null)
        setDraft('')
        if (added.domains) {
            onUpdate(config.id, {
                allowed_domains: added.domains,
                // The mode and its first domain have to land in one request, because the API rejects
                // custom access with nothing to reach.
                ...(isCustom ? {} : { network_access: SignalScoutConfigNetworkAccessEnumApi.Custom }),
            })
        }
    }

    const removeDomain = (domain: string): void => {
        if (updating) {
            return
        }
        const nextDomains = withScoutDomainRemoved(domains, domain)
        if (!nextDomains) {
            return
        }
        if (nextDomains.length === 0 && isCustom) {
            setError('Add another domain first, or pick a different network access mode.')
            return
        }
        setError(null)
        onUpdate(config.id, { allowed_domains: nextDomains })
    }

    return (
        <div className="flex flex-col gap-1">
            <div className="flex flex-wrap items-center gap-1">
                {domains.map((domain) => (
                    <LemonTag
                        key={domain}
                        type="highlight"
                        size="small"
                        closable={!updating}
                        onClose={() => removeDomain(domain)}
                    >
                        {domain}
                    </LemonTag>
                ))}
                <LemonInput
                    value={draft}
                    onChange={(value) => {
                        setDraft(value)
                        setError(null)
                    }}
                    onBlur={commitDraft}
                    onKeyDown={(event) => {
                        if (event.key === 'Enter' || event.key === ',') {
                            event.preventDefault()
                            commitDraft()
                        } else if (event.key === 'Backspace' && draft === '' && domains.length > 0) {
                            event.preventDefault()
                            removeDomain(domains[domains.length - 1])
                        }
                    }}
                    size="xsmall"
                    placeholder={atCap ? `${MAX_SCOUT_ALLOWED_DOMAINS} domain limit` : 'Add domain'}
                    aria-label={`${config.skill_name} allowed domains`}
                    disabledReason={
                        updating
                            ? 'Saving scout settings'
                            : atCap
                              ? `A scout can reach up to ${MAX_SCOUT_ALLOWED_DOMAINS} custom domains`
                              : undefined
                    }
                    status={error ? 'danger' : 'default'}
                    className="w-56"
                />
            </div>
            {error ? (
                <span role="alert" className="text-xs text-danger">
                    {error}
                </span>
            ) : (
                <span className="text-[11.5px] text-muted">
                    One domain per entry, like status.example.com, with no scheme or path. Use *.example.com to cover
                    every subdomain. Trusted domains are always included.
                </span>
            )}
        </div>
    )
}
