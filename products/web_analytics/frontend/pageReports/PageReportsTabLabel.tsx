import { useActions, useValues } from 'kea'

import * as megaphonePng from '@posthog/brand/hoggies/png/megaphone'
import { Tooltip } from '@posthog/lemon-ui'

import { pngHoggie } from 'lib/brand/hoggies'

import { pageReportsTeaserLogic } from './pageReportsTeaserLogic'

const MegaphoneHog = pngHoggie(megaphonePng)

export function PageReportsTabLabel(): JSX.Element {
    const { showTeaser } = useValues(pageReportsTeaserLogic)
    const { hoverTeaser } = useActions(pageReportsTeaserLogic)

    if (!showTeaser) {
        return <>Page reports</>
    }

    return (
        <Tooltip
            title={
                <div className="flex flex-col gap-1 max-w-60">
                    <span className="font-semibold">New and improved!</span>
                    <span>
                        Page reports now lists every page with its Google and AI traffic. Open any page for its full
                        report.
                    </span>
                </div>
            }
            placement="bottom"
        >
            <span className="group inline-flex items-center" onMouseEnter={hoverTeaser} data-attr="page-reports-teaser">
                <span className="relative z-10">Page reports</span>
                <span className="relative -my-3 -ml-2 h-7 w-8 translate-y-0.5 overflow-hidden" aria-hidden>
                    <MegaphoneHog
                        className="absolute left-0 top-2.5 w-8 rotate-6 transition-transform duration-300 ease-out group-hover:-translate-y-2 group-hover:rotate-0 motion-reduce:transition-none"
                        loading="eager"
                    />
                </span>
            </span>
        </Tooltip>
    )
}
