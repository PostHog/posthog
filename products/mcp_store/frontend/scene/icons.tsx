import { IconServer } from '@posthog/icons'

import IconAirOpsService from 'public/services/airops.png'
import IconAtlassianService from 'public/services/atlassian.svg'
import IconAttioService from 'public/services/attio.png'
import IconBoxService from 'public/services/box.svg'
import IconBrowserbaseService from 'public/services/browserbase.svg'
import IconCanvaService from 'public/services/canva.svg'
import IconCircleService from 'public/services/circle.png'
import IconCiscoThousandEyesService from 'public/services/cisco_thousandeyes.png'
import IconClerkService from 'public/services/clerk.svg'
import IconClickHouseService from 'public/services/clickhouse.svg'
import IconCloudflareService from 'public/services/cloudflare.svg'
import IconContext7Service from 'public/services/context7.svg'
import IconDatadogService from 'public/services/datadog.svg'
import IconFigmaService from 'public/services/figma.svg'
import IconFiretigerService from 'public/services/firetiger.svg'
import IconGitHubService from 'public/services/github.svg'
import IconGitLabService from 'public/services/gitlab.svg'
import IconHexService from 'public/services/hex.svg'
import IconHubSpotService from 'public/services/hubspot.png'
import IconLaunchDarklyService from 'public/services/launchdarkly.png'
import IconLinearService from 'public/services/linear.svg'
import IconMondayService from 'public/services/monday.svg'
import IconNeonService from 'public/services/neon.svg'
import IconNotionService from 'public/services/notion.svg'
import IconPagerDutyService from 'public/services/pagerduty.svg'
import IconPlanetScaleService from 'public/services/planetscale.svg'
import IconPostmanService from 'public/services/postman.svg'
import IconPrismaService from 'public/services/prisma.svg'
import IconRenderService from 'public/services/render.svg'
import IconSanityService from 'public/services/sanity.svg'
import IconSentryService from 'public/services/sentry.svg'
import IconSlackService from 'public/services/slack.png'
import IconStripeService from 'public/services/stripe.png'
import IconSupabaseService from 'public/services/supabase.svg'
import IconSvelteService from 'public/services/svelte.png'
import IconWixService from 'public/services/wix.png'

// Templates without an asset here use the generic server icon.
const SERVER_ICONS: Record<string, string> = {
    airops: IconAirOpsService,
    atlassian: IconAtlassianService,
    attio: IconAttioService,
    box: IconBoxService,
    browserbase: IconBrowserbaseService,
    canva: IconCanvaService,
    cisco_thousandeyes: IconCiscoThousandEyesService,
    circle: IconCircleService,
    clerk: IconClerkService,
    clickhouse: IconClickHouseService,
    cloudflare: IconCloudflareService,
    context7: IconContext7Service,
    datadog: IconDatadogService,
    figma: IconFigmaService,
    firetiger: IconFiretigerService,
    github: IconGitHubService,
    gitlab: IconGitLabService,
    hex: IconHexService,
    hubspot: IconHubSpotService,
    launchdarkly: IconLaunchDarklyService,
    linear: IconLinearService,
    monday: IconMondayService,
    neon: IconNeonService,
    notion: IconNotionService,
    pagerduty: IconPagerDutyService,
    planetscale: IconPlanetScaleService,
    postman: IconPostmanService,
    prisma: IconPrismaService,
    render: IconRenderService,
    sanity: IconSanityService,
    sentry: IconSentryService,
    slack: IconSlackService,
    stripe: IconStripeService,
    supabase: IconSupabaseService,
    svelte: IconSvelteService,
    wix: IconWixService,
}

export function resolveServerIcon(iconKey: string | null | undefined): string | undefined {
    return iconKey ? SERVER_ICONS[iconKey] : undefined
}

interface ServerIconProps {
    iconKey?: string | null
    size?: number
    className?: string
}

export function ServerIcon({ iconKey, size = 32, className }: ServerIconProps): JSX.Element {
    const src = resolveServerIcon(iconKey)
    const dimension = `${size}px`
    if (src) {
        return (
            <div
                className={`flex items-center justify-center overflow-hidden rounded-[4px] ${className ?? ''}`}
                // Fixed dimensions prevent layout shift during icon load.
                style={{ width: dimension, height: dimension }}
            >
                <img src={src} alt="" style={{ width: dimension, height: dimension }} />
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
