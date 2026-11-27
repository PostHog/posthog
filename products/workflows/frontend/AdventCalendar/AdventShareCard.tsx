import './AdventCalendar.scss'
import './AdventShareCard.scss'

import { forwardRef } from 'react'

import { ADVENT_LAST_DAY } from './adventContent'
import type { AdventGraph } from './adventGraph'
import { adventPaletteStyle } from './adventPalette'
import { AdventPictureBackdrop } from './AdventPictureBackdrop'
import { AdventPictureCast } from './AdventPictureCast'

export interface AdventShareCardProps {
    graph: AdventGraph
    openCount: number
}

export const AdventShareCard = forwardRef<HTMLDivElement, AdventShareCardProps>(function AdventShareCard(
    { graph, openCount },
    ref
): JSX.Element {
    return (
        <div ref={ref} className="AdventShare" style={adventPaletteStyle()} data-attr="advent-share-card">
            <div className="AdventShare__sheet">
                <div className="AdventPicture AdventShare__picture">
                    <AdventPictureBackdrop graph={graph} hasTracks />
                    <AdventPictureCast graph={graph} />
                </div>
                <div className="AdventShare__plaque">
                    <span className="AdventShare__eyebrow">{`${openCount} of ${ADVENT_LAST_DAY} doors open`}</span>
                    <span className="AdventShare__headline" translate="no">
                        A very merry PostHog
                    </span>
                    <span className="AdventShare__label">Made with PostHog Workflows</span>
                </div>
                <span className="AdventShare__rule" />
            </div>
        </div>
    )
})
