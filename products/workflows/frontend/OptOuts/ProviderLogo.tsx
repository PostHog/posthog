import { IconUpload } from '@posthog/icons'

const PROVIDER_LOGOS: Record<string, string> = {
    customerio: '/static/services/customerio.png',
    mailgun: '/static/services/mailgun.png',
    postmark: '/static/services/postmark.png',
    resend: '/static/services/resend.png',
    sendgrid: '/static/services/sendgrid.png',
}

export function ProviderLogo({ providerKey }: { providerKey: string }): JSX.Element {
    const src = PROVIDER_LOGOS[providerKey]
    // The tool's name sits next to the logo, so screen readers skip the image.
    return src ? (
        <img src={src} alt="" className="size-8 shrink-0 rounded" />
    ) : (
        <span className="flex size-8 shrink-0 items-center justify-center rounded border text-lg text-secondary">
            <IconUpload />
        </span>
    )
}
