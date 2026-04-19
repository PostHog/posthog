import { Box, Icon, Inline, Link } from '@stripe/ui-extension-sdk/ui'

interface Props {
    href: string
    children: React.ReactNode
}

const ExternalLink = ({ href, children }: Props): JSX.Element => (
    <Link href={href} target="_blank" external>
        <Box css={{ stack: 'x', columnGap: 'xxsmall', alignY: 'center' }}>
            <Inline>{children}</Inline>
            <Icon name="external" size="xsmall" />
        </Box>
    </Link>
)

export default ExternalLink
