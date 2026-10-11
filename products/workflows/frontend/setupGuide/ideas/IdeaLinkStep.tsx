import { IconCheckCircle, IconWarning } from '@posthog/icons'

import { siteHost } from './ideaCopy'

/** One checklist line saying where an idea's email buttons link. */
export function IdeaLinkStep({ siteUrl }: { siteUrl: string | null | undefined }): JSX.Element {
    const host = siteHost(siteUrl)
    return host ? (
        <li className="flex items-start gap-2">
            <IconCheckCircle className="mt-0.5 shrink-0 text-success" />
            <span>
                Buttons link to <strong>{host}</strong>. You can point them at an exact page in the editor.
            </span>
        </li>
    ) : (
        <li className="flex items-start gap-2">
            <IconWarning className="mt-0.5 shrink-0 text-warning" />
            <span>The email buttons have no link yet. Set them in the editor.</span>
        </li>
    )
}
