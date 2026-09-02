import { IconInfo } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'

import { visionDocsUrl } from './DocsLink'

/**
 * The dock sits on every standard replay player, so it reaches people who have never heard of Replay
 * vision and meet the summarize button with no idea what it is or what it will spend.
 */
export function SummarizeExplainer(): JSX.Element {
    return (
        <Tooltip
            placement="bottom"
            // Base UI opens tooltips on hover only, which leaves this unreachable on a touch device.
            openOnClick
            title={
                <>
                    <p className="mb-1">Replay vision uses AI to watch recordings for you.</p>
                    <p className="mb-0">
                        Summarizing writes up what the user did in this session, so you can read it instead of watching
                        it.
                    </p>
                </>
            }
            docLink={`${visionDocsUrl()}?utm_medium=in-product&utm_campaign=summarize-explainer`}
        >
            <span className="inline-flex items-center text-muted" data-attr="vision-summarize-info">
                <IconInfo />
            </span>
        </Tooltip>
    )
}
