import { Box, Img, Inline, Link } from '@stripe/ui-extension-sdk/ui'

import { POSTHOG_ICON_SRC } from '../../constants'

interface Props {
    children: React.ReactNode
    /** When set, renders a large centered logo above the content */
    hero?: boolean
}

const PromoBanner = ({ children, hero }: Props): JSX.Element => (
    <Box
        css={{
            stack: 'y',
            rowGap: hero ? 'medium' : 'xsmall',
            padding: hero ? 'xlarge' : 'medium',
            borderRadius: 'medium',
            backgroundColor: 'container',
            ...(hero ? { alignX: 'center' as const } : {}),
        }}
    >
        {hero && (
            <Box css={{ stack: 'x', alignX: 'center' }}>
                <Img src={POSTHOG_ICON_SRC} alt="PostHog" width="48" height="28" />
            </Box>
        )}
        {children}
    </Box>
)

export default PromoBanner

export const PromoBannerText = ({ children }: { children: React.ReactNode }): JSX.Element => (
    <Inline css={{ font: 'body', color: 'secondary' }}>{children}</Inline>
)

export const PromoBannerTitle = ({ children }: { children: React.ReactNode }): JSX.Element => (
    <Inline css={{ font: 'heading' }}>{children}</Inline>
)

export const PromoBannerLink = ({ href, children }: { href: string; children: React.ReactNode }): JSX.Element => (
    <Link href={href} target="_blank" external>
        <Inline css={{ font: 'caption' }}>{children}</Inline>
    </Link>
)

export const PromoBannerPrimaryLink = ({
    href,
    children,
}: {
    href: string
    children: React.ReactNode
}): JSX.Element => (
    <Link href={href} target="_blank" type="primary">
        {children}
    </Link>
)
