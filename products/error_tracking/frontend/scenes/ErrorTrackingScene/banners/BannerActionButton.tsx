import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { Button } from 'lib/ui/quill'

export interface BannerAction {
    label: string
    icon?: JSX.Element
    onClick?: () => void
    to?: string
    targetBlank?: boolean
    dataAttr: string
}

export function BannerActionButton({
    action,
    variant,
}: {
    action: BannerAction
    variant: 'primary' | 'default'
}): JSX.Element {
    return (
        <Button
            variant={variant}
            onClick={action.onClick}
            data-attr={action.dataAttr}
            render={
                action.to ? (
                    <LinkPrimitive to={action.to} target={action.targetBlank ? '_blank' : undefined} />
                ) : undefined
            }
        >
            {action.icon}
            {action.label}
        </Button>
    )
}
