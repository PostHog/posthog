import { IconServer } from '@posthog/icons'

import IconPostHogService from 'public/posthog-icon.svg'
import IconAtlassianService from 'public/services/atlassian.svg'
import IconAttioService from 'public/services/attio.png'
import IconCanvaService from 'public/services/canva.svg'
import IconGitHubService from 'public/services/github.svg'
import IconLinearService from 'public/services/linear.svg'
import IconMondayService from 'public/services/monday.svg'
import IconNotionService from 'public/services/notion.svg'

// Brand icons keyed by either the server's `icon_key` (preferred) or its
// display name (fallback for older templates without an explicit key).
const SERVER_ICONS: Record<string, string> = {
    PostHog: IconPostHogService,
    'PostHog MCP': IconPostHogService,
    Linear: IconLinearService,
    GitHub: IconGitHubService,
    Notion: IconNotionService,
    Monday: IconMondayService,
    Canva: IconCanvaService,
    Attio: IconAttioService,
    Atlassian: IconAtlassianService,
}

export function resolveServerIcon(...keys: (string | null | undefined)[]): string | undefined {
    for (const key of keys) {
        if (key && SERVER_ICONS[key]) {
            return SERVER_ICONS[key]
        }
    }
    return undefined
}

interface ServerIconProps {
    iconKey?: string | null
    name?: string | null
    size?: number
    className?: string
}

export function ServerIcon({ iconKey, name, size = 32, className }: ServerIconProps): JSX.Element {
    const src = resolveServerIcon(iconKey, name)
    const dimension = `${size}px`
    if (src) {
        return (
            <div
                className={`flex items-center justify-center ${className ?? ''}`}
                // Fixed dimensions prevent layout shift during icon load.
                style={{ width: dimension, height: dimension }}
            >
                <img src={src} alt="" style={{ width: dimension, height: dimension }} />
            </div>
        )
    }
    return (
        <div
            className={`flex items-center justify-center rounded bg-surface-secondary ${className ?? ''}`}
            style={{ width: dimension, height: dimension }}
        >
            <IconServer className="text-secondary" style={{ fontSize: size * 0.55 }} />
        </div>
    )
}
