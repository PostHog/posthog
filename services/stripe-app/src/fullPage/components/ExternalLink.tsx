import { Link } from '@stripe/ui-extension-sdk/ui'

interface Props {
    href: string
    children: React.ReactNode
}

const ExternalLink = ({ href, children }: Props): JSX.Element => (
    <Link href={href} target="_blank" external>
        {children}
    </Link>
)

export default ExternalLink
