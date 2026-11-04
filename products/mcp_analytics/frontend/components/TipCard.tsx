import { IconExternal } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

export interface TipCardLink {
    label: string
    to: string
    dataAttr: string
    onClick?: () => void
}

export function TipCard({ title, body, link }: { title: string; body: string; link: TipCardLink }): JSX.Element {
    return (
        <div className="flex flex-col items-start gap-1 rounded border border-primary bg-surface-primary p-4 text-sm">
            <span className="text-base font-semibold">{title}</span>
            <span className="text-secondary">{body}</span>
            <LemonButton
                className="mt-2"
                size="small"
                type="secondary"
                to={link.to}
                targetBlank
                sideIcon={<IconExternal />}
                onClick={link.onClick}
                data-attr={link.dataAttr}
            >
                {link.label}
            </LemonButton>
        </div>
    )
}
