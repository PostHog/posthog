import { useState } from 'react'

import { IconServer } from '@posthog/icons'

// Machine-facing subdomains stripped when deriving a brand domain from a server URL, so a custom
// install at https://mcp.linear.app/mcp still resolves the vendor's brand (linear.app).
const STRIPPED_SUBDOMAINS = ['mcp.', 'api.', 'www.']

export function iconDomainFromServerUrl(serverUrl: string | null | undefined): string | null {
    if (!serverUrl) {
        return null
    }
    let host: string
    try {
        host = new URL(serverUrl).hostname.toLowerCase()
    } catch {
        return null
    }
    for (const prefix of STRIPPED_SUBDOMAINS) {
        if (host.startsWith(prefix) && host.split('.').length >= 3) {
            return host.slice(prefix.length)
        }
    }
    return host.includes('.') ? host : null
}

export function serverIconUrl(iconDomain: string): string {
    return `/api/projects/@current/mcp_servers/icon/?domain=${encodeURIComponent(iconDomain)}`
}

interface ServerIconProps {
    /** The template's brand domain (icon_domain). Falls back to deriving one from serverUrl. */
    iconDomain?: string | null
    /** The MCP server URL — lets custom installs without a template still get a brand icon. */
    serverUrl?: string | null
    size?: number
    className?: string
}

export function ServerIcon({ iconDomain, serverUrl, size = 32, className }: ServerIconProps): JSX.Element {
    const domain = iconDomain || iconDomainFromServerUrl(serverUrl)
    const [failedDomain, setFailedDomain] = useState<string | null>(null)
    const dimension = `${size}px`
    if (domain && failedDomain !== domain) {
        return (
            <div
                className={`flex items-center justify-center overflow-hidden rounded-[4px] ${className ?? ''}`}
                // Fixed dimensions prevent layout shift during icon load.
                style={{ width: dimension, height: dimension }}
            >
                <img
                    src={serverIconUrl(domain)}
                    alt=""
                    style={{ width: dimension, height: dimension }}
                    onError={() => setFailedDomain(domain)}
                />
            </div>
        )
    }
    return (
        <div
            className={`flex items-center justify-center rounded-[4px] bg-surface-secondary ${className ?? ''}`}
            style={{ width: dimension, height: dimension }}
        >
            <IconServer className="text-secondary" style={{ fontSize: size * 0.55 }} />
        </div>
    )
}
