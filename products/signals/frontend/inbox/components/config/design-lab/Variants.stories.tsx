import type { Meta, StoryObj } from '@storybook/react'

import { LabScenario, LabSource, sourcesFor } from './contract'
import { VariantA, WIDTH_A } from './variantA'
import { VariantB, WIDTH_B } from './variantB'
import { VariantB1, WIDTH_B1 } from './variantB1'
import { VariantB2, WIDTH_B2 } from './variantB2'
import { VariantB3, WIDTH_B3 } from './variantB3'
import { VariantC, WIDTH_C } from './variantC'
import { VariantD, WIDTH_D } from './variantD'

/**
 * THROWAWAY design lab for the Signal sources panel. Not committed.
 *
 * Every tile renders the same fixture from `contract.ts`, so the grid compares design only.
 */
const meta: Meta = {
    title: 'DesignLab/SignalSources',
    id: 'designlab-signalsources',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2024-03-20',
        testOptions: { skip: true },
    },
}
export default meta

type VariantComponent = (props: { sources: LabSource[]; scenario: LabScenario }) => JSX.Element

/** Frames a variant the way the real setup modal does, at the width that variant asks for. */
function ModalFrame({
    Variant,
    width,
    scenario,
}: {
    Variant: VariantComponent
    width: number
    scenario: LabScenario
}): JSX.Element {
    return (
        <div className="bg-surface-primary border border-primary rounded shadow-lg" style={{ width }}>
            <div className="px-6 pt-5 pb-3">
                <h3 className="text-lg font-semibold mb-1">Signal sources</h3>
                <p className="text-sm text-secondary mb-0">
                    Each source watches for signals, and spins up an agent to look into them.
                </p>
            </div>
            <div className="border-t border-primary px-6 py-4">
                <Variant sources={sourcesFor(scenario)} scenario={scenario} />
            </div>
        </div>
    )
}

const story = (Variant: VariantComponent, width: number, scenario: LabScenario): StoryObj => ({
    render: () => (
        <div className="min-h-screen w-full bg-primary p-6 flex justify-center items-start">
            <ModalFrame Variant={Variant} width={width} scenario={scenario} />
        </div>
    ),
})

export const AVariant: StoryObj = story(VariantA, WIDTH_A, 'typical')
export const BVariant: StoryObj = story(VariantB, WIDTH_B, 'typical')
export const CVariant: StoryObj = story(VariantC, WIDTH_C, 'typical')
export const DVariant: StoryObj = story(VariantD, WIDTH_D, 'typical')
export const B1Variant: StoryObj = story(VariantB1, WIDTH_B1, 'typical')
export const B2Variant: StoryObj = story(VariantB2, WIDTH_B2, 'typical')
export const B3Variant: StoryObj = story(VariantB3, WIDTH_B3, 'typical')

export const AVariantHeavy: StoryObj = story(VariantA, WIDTH_A, 'heavy')
export const BVariantHeavy: StoryObj = story(VariantB, WIDTH_B, 'heavy')
export const CVariantHeavy: StoryObj = story(VariantC, WIDTH_C, 'heavy')
export const DVariantHeavy: StoryObj = story(VariantD, WIDTH_D, 'heavy')
export const B1VariantHeavy: StoryObj = story(VariantB1, WIDTH_B1, 'heavy')

export const AVariantNothingOn: StoryObj = story(VariantA, WIDTH_A, 'nothingOn')
export const BVariantNothingOn: StoryObj = story(VariantB, WIDTH_B, 'nothingOn')
export const CVariantNothingOn: StoryObj = story(VariantC, WIDTH_C, 'nothingOn')
export const DVariantNothingOn: StoryObj = story(VariantD, WIDTH_D, 'nothingOn')

interface Tile {
    label: string
    bet: string
    Variant: VariantComponent
    width: number
}

const ROUND_ONE: Tile[] = [
    { label: 'A: Scout-style rows', bet: 'Match the Scout panel next door.', Variant: VariantA, width: WIDTH_A },
    {
        label: 'B: Dense control board',
        bet: 'This is a control panel, not a catalog.',
        Variant: VariantB,
        width: WIDTH_B,
    },
    { label: 'C: Watcher-first list', bet: 'You manage watchers, not products.', Variant: VariantC, width: WIDTH_C },
    { label: 'D: Two-pane settings', bet: 'Settings shape, so use two panes.', Variant: VariantD, width: WIDTH_D },
]

const ROUND_TWO: Tile[] = [
    { label: 'B: as built, densest', bet: 'One line per source, nothing spare.', Variant: VariantB, width: WIDTH_B },
    { label: 'B1: gloss on a second line', bet: 'A gloss under each name.', Variant: VariantB1, width: WIDTH_B1 },
    { label: 'B2: gloss on the same line', bet: 'A gloss beside each name.', Variant: VariantB2, width: WIDTH_B2 },
    { label: 'B3: labelled columns', bet: 'A header explains the columns once.', Variant: VariantB3, width: WIDTH_B3 },
]

const TILE_H = 1120
const SCALE = 0.5

/**
 * Renders each variant inline and scales it, rather than in an iframe.
 *
 * The harness normally needs an iframe per tile, because several copies of the app fight over one
 * store and one router. These variants hold only local state, so they can share a document, and
 * the tiles then paint immediately instead of booting Storybook four times.
 */
function Grid({ tiles, scenario, note }: { tiles: Tile[]; scenario: LabScenario; note: string }): JSX.Element {
    return (
        <div className="min-h-screen bg-primary p-4">
            <p className="text-sm text-secondary mb-3">{note}</p>
            <div className="grid grid-cols-2 gap-4">
                {tiles.map(({ label, bet, Variant, width }) => (
                    <div key={label}>
                        <div className="font-semibold text-sm">{label}</div>
                        <div className="text-xs text-muted mb-1.5">{bet}</div>
                        <div
                            className="overflow-hidden rounded border border-primary bg-primary"
                            style={{ height: TILE_H * SCALE }}
                        >
                            <div
                                className="flex justify-center p-4"
                                style={{
                                    width: `${100 / SCALE}%`,
                                    height: TILE_H,
                                    transform: `scale(${SCALE})`,
                                    transformOrigin: 'top left',
                                }}
                            >
                                <ModalFrame Variant={Variant} width={width} scenario={scenario} />
                            </div>
                        </div>
                    </div>
                ))}
            </div>
        </div>
    )
}

/** Round one: four whole-panel designs, safe to strange. */
export const AllVariants: StoryObj = {
    render: () => (
        <Grid
            tiles={ROUND_ONE}
            scenario="typical"
            note="Round one. Typical project: 3 scanners, 4 evaluations, 3 error tracking signal types."
        />
    ),
}

export const AllVariantsHeavy: StoryObj = {
    render: () => (
        <Grid
            tiles={ROUND_ONE}
            scenario="heavy"
            note="Round one, tail case: 63 scanners under Replay vision, the p99 of real projects."
        />
    ),
}

export const AllVariantsNothingOn: StoryObj = {
    render: () => <Grid tiles={ROUND_ONE} scenario="nothingOn" note="Round one, first run: nothing watching yet." />,
}

/** Round two: how far to walk the winner toward being self-explanatory. */
export const BDensity: StoryObj = {
    render: () => (
        <Grid
            tiles={ROUND_TWO}
            scenario="typical"
            note="Round two. The same board at four densities, differing only in how much each row explains itself."
        />
    ),
}

export const BDensityHeavy: StoryObj = {
    render: () => <Grid tiles={ROUND_TWO} scenario="heavy" note="Round two with 63 scanners." />,
}

export const BDensityNothingOn: StoryObj = {
    render: () => <Grid tiles={ROUND_TWO} scenario="nothingOn" note="Round two on first run." />,
}
