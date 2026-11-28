import { memo } from 'react'

import { ADVENT_PICTURE, adventDoorGround, AdventGraph, openDoors } from './adventGraph'
import { adventPalette, adventStroke } from './adventPalette'
import { AdventVillageArt } from './AdventVillageArt'

export interface AdventPictureBackdropProps {
    graph: AdventGraph
    hasTracks: boolean
}

export const AdventPictureBackdrop = memo(function AdventPictureBackdrop({
    graph,
    hasTracks,
}: AdventPictureBackdropProps): JSX.Element {
    const palette = adventPalette()
    const steps = openDoors(graph).map(adventDoorGround)

    return (
        <>
            <AdventVillageArt palette={palette} />
            {hasTracks && steps.length > 1 && (
                <svg
                    viewBox={`0 0 ${ADVENT_PICTURE.width} ${ADVENT_PICTURE.height}`}
                    width="100%"
                    height="100%"
                    className="absolute inset-0"
                    aria-hidden
                >
                    <path
                        d={`M${steps.map((step) => `${step.x} ${step.y - 4}`).join(' L')}`}
                        {...adventStroke(palette.blue, 5)}
                        strokeDasharray="1 11"
                        opacity={0.7}
                    />
                </svg>
            )}
        </>
    )
})
