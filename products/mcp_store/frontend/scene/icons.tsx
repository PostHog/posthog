import { useValues } from 'kea'
import { useState } from 'react'

import { IconServer } from '@posthog/icons'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'

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

export function serverIconUrl(iconDomain: string, theme?: 'light' | 'dark'): string {
    const themeSuffix = theme ? `&theme=${theme}` : ''
    return `/api/projects/@current/mcp_servers/icon/?domain=${encodeURIComponent(iconDomain)}${themeSuffix}`
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
    const { isDarkModeOn } = useValues(themeLogic)
    const domain = iconDomain || iconDomainFromServerUrl(serverUrl)
    // logo.dev picks the logo variant suited to the active background theme.
    const theme = isDarkModeOn ? 'dark' : 'light'
    // Failure latches per (domain, theme) — the unit the request URL varies over — so a failed
    // load in one theme doesn't blank the other, and a theme flip retries after a transient error
    // (cheap: definitive misses are cached server-side for a day).
    const iconKey = `${domain}|${theme}`
    const [failedIconKey, setFailedIconKey] = useState<string | null>(null)
    const dimension = `${size}px`
    if (domain && failedIconKey !== iconKey) {
        return (
            <div
                className={`flex items-center justify-center overflow-hidden rounded-[4px] ${className ?? ''}`}
                // Fixed dimensions prevent layout shift during icon load.
                style={{ width: dimension, height: dimension }}
            >
                <img
                    src={serverIconUrl(domain, theme)}
                    alt=""
                    style={{ width: dimension, height: dimension }}
                    onError={() => setFailedIconKey(iconKey)}
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
