import { useActions, useValues } from 'kea'

import { LemonModal } from '@posthog/lemon-ui'

import { useWindowSize } from 'lib/hooks/useWindowSize'

import { reviewHogSettingsLogic } from './reviewHogSettingsLogic'

/**
 * "Detailed view" of the review pipeline, opened from the "How we review your PRs" section.
 * The diagram is a fixed 1280×720 canvas recreated from the design handoff with a hardcoded dark
 * palette — it renders identically in light and dark theme (treat it as artwork; its contrast was
 * tuned against this exact background) and scales down uniformly instead of reflowing.
 */

const CANVAS_W = 1280
const CANVAS_H = 720

/** LemonModal's vertical chrome: its max-height offset (60px + 2rem) plus its 1rem top/bottom margins. */
const MODAL_VERTICAL_CHROME_PX = 124
/** Scale floor: in a viewport shorter than the modal chrome the canvas overflows, not collapses. */
const MIN_SCALE = 0.1

/** Shared lane centers: chunk cards, validate cards, and every connector line up on these. */
const LANES = ['16.667%', '50%', '83.333%'] as const

/** Perspectives stay abstract (A/B/C) on purpose: rosters differ per user, the modal teaches the logic. */
const PERSPECTIVE_NAMES = ['Perspective A', 'Perspective B', 'Perspective C']
const CHUNK_PICKS: boolean[][] = [
    [true, true, false],
    [true, false, true],
    [true, true, true],
]

function DashedDrop({ left, top, height }: { left: string; top: number; height: number }): JSX.Element {
    return (
        <div
            className="absolute w-0 -translate-x-1/2 border-l-2 border-dashed border-[#3a3f46]"
            style={{ left, top, height }}
        />
    )
}

function ArrowHead({ left }: { left: string }): JSX.Element {
    return (
        <div
            className="absolute h-0 w-0 -translate-x-1/2"
            style={{
                left,
                top: 21,
                borderLeft: '5px solid transparent',
                borderRight: '5px solid transparent',
                borderTop: '7px solid #3a3f46',
            }}
        />
    )
}

function DashedRail({ left, right }: { left: string; right: string }): JSX.Element {
    return (
        <div
            className="absolute h-0.5"
            style={{
                left,
                right,
                top: 13,
                backgroundImage: 'repeating-linear-gradient(90deg, rgba(93,100,109,0.5) 0 6px, transparent 6px 15px)',
            }}
        />
    )
}

/** 03 → chunk cards: a stub from under the "Pick perspectives" box feeds the distribution rail. */
function FanOutConnector(): JSX.Element {
    return (
        <div className="relative my-1.5 h-8" aria-hidden="true">
            <DashedDrop left="85.5%" top={4} height={9} />
            <DashedRail left={LANES[0]} right="14.5%" />
            {LANES.map((lane) => (
                <DashedDrop key={lane} left={lane} top={13} height={8} />
            ))}
            {LANES.map((lane) => (
                <ArrowHead key={lane} left={lane} />
            ))}
        </div>
    )
}

/** Straight per-lane drops (chunks → dedupe, dedupe → validate). */
function LaneConnector(): JSX.Element {
    return (
        <div className="relative my-1.5 h-8" aria-hidden="true">
            {LANES.map((lane) => (
                <DashedDrop key={lane} left={lane} top={4} height={17} />
            ))}
            {LANES.map((lane) => (
                <ArrowHead key={lane} left={lane} />
            ))}
        </div>
    )
}

/** Validate lanes → the single published review. */
function MergeConnector(): JSX.Element {
    return (
        <div className="relative my-1.5 h-8" aria-hidden="true">
            <DashedDrop left={LANES[0]} top={4} height={9} />
            <DashedDrop left={LANES[2]} top={4} height={9} />
            <DashedDrop left={LANES[1]} top={4} height={17} />
            <DashedRail left={LANES[0]} right={LANES[0]} />
            <ArrowHead left={LANES[1]} />
        </div>
    )
}

function SequenceArrow(): JSX.Element {
    return <div className="text-center text-[15px] text-[#5f656c]">→</div>
}

function StepBox({ number, title, caption }: { number: string; title: string; caption?: string }): JSX.Element {
    return (
        <div className="rounded-lg border border-[#34383f] bg-[#212429] px-3 py-2.5">
            <span className="mr-2 font-mono text-[11px] tracking-[0.1em] text-[#f0a009]">{number}</span>
            <span className="text-[12.5px] font-semibold">{title}</span>
            {caption && <span className="text-xs text-[#b3b9c0]"> · {caption}</span>}
        </div>
    )
}

function ChunkCard({ index }: { index: number }): JSX.Element {
    return (
        <div className="rounded-[9px] border border-[#2a2d32] bg-[#1c1f23] px-3 py-2.5">
            <div className="mb-[7px] font-mono text-xs text-[#b3b9c0]">CHUNK {index + 1}</div>
            <div className="flex flex-nowrap gap-[5px]">
                {PERSPECTIVE_NAMES.map((name, i) =>
                    CHUNK_PICKS[index][i] ? (
                        <span
                            key={name}
                            className="whitespace-nowrap rounded-md border border-[rgba(240,160,9,0.4)] bg-[rgba(240,160,9,0.08)] px-2 py-[3px] text-xs font-medium text-white"
                        >
                            {name}
                        </span>
                    ) : (
                        <span
                            key={name}
                            className="whitespace-nowrap rounded-md border border-dashed border-[#3c4148] px-2 py-[3px] text-xs text-[#7d848c]"
                        >
                            {name} · not needed
                        </span>
                    )
                )}
            </div>
            <div className="mb-[5px] mt-1.5 text-center text-xs leading-none text-[#7d848c]">↓</div>
            <div className="flex items-baseline justify-center gap-[7px] rounded-md border border-[#383d44] bg-[#262a30] px-2 py-[5px]">
                <span className="text-xs font-semibold">Blind spot</span>
                <span className="text-[11px] text-[#b3b9c0]">sweeps what the perspectives missed</span>
            </div>
        </div>
    )
}

function ValidateCard({ index }: { index: number }): JSX.Element {
    return (
        <div className="rounded-lg border border-[#2a2d32] bg-[#212429] px-3 py-2.5">
            <div className="flex items-baseline gap-2">
                <span className="font-mono text-[11px] text-[#b3b9c0]">CHUNK {index + 1}</span>
                <span className="text-xs font-semibold">Validate</span>
            </div>
            <div className="mt-0.5 text-[11.5px] text-[#b3b9c0]">warm session · one verdict per finding</div>
        </div>
    )
}

function GoldBandNumber({ children }: { children: string }): JSX.Element {
    return <span className="font-mono text-[#f0a009]">{children}</span>
}

export function PipelineDetailModal(): JSX.Element {
    const { pipelineDetailOpen } = useValues(reviewHogSettingsLogic)
    const { closePipelineDetail } = useActions(reviewHogSettingsLogic)
    const { windowSize } = useWindowSize()

    // LemonModal caps itself at 90% of the viewport width and just under the viewport height; fit
    // the fixed-ratio canvas inside those bounds, never upscaling past the designed size.
    const scale = Math.max(
        MIN_SCALE,
        Math.min(
            1,
            ((windowSize.width ?? CANVAS_W) * 0.9) / CANVAS_W,
            ((windowSize.height ?? CANVAS_H + MODAL_VERTICAL_CHROME_PX) - MODAL_VERTICAL_CHROME_PX) / CANVAS_H
        )
    )

    return (
        <LemonModal
            isOpen={pipelineDetailOpen}
            onClose={closePipelineDetail}
            simple
            hideCloseButton
            className="overflow-hidden rounded-xl border-[#2c2f35] bg-[#17191d] shadow-[0_32px_90px_rgba(0,0,0,0.65)]"
            data-attr="review-pipeline-detail-modal"
        >
            <div style={{ width: CANVAS_W * scale, height: CANVAS_H * scale }}>
                <div
                    className="flex flex-col text-[#f2f3f5]"
                    style={{
                        width: CANVAS_W,
                        height: CANVAS_H,
                        transform: `scale(${scale})`,
                        transformOrigin: 'top left',
                    }}
                >
                    <div className="flex flex-none items-center justify-between border-b border-[#25282d] px-[22px] py-4">
                        <div>
                            <div className="text-[15px] font-bold">How we review your PRs</div>
                            <div className="mt-0.5 text-xs text-[#b3b9c0]">
                                Every review runs through the same steps before it's published.
                            </div>
                        </div>
                        <button
                            type="button"
                            aria-label="Close"
                            onClick={closePipelineDetail}
                            className="flex size-[26px] cursor-pointer items-center justify-center rounded-md border border-[#34383f] text-sm text-[#b3b9c0] transition-colors hover:border-[#4a4f57] hover:text-[#f2f3f5]"
                        >
                            ×
                        </button>
                    </div>

                    <div className="flex flex-1 flex-col justify-center px-11 py-4">
                        <div
                            className="grid items-center"
                            style={{ gridTemplateColumns: '90px 24px 1fr 24px 1fr 24px 1.2fr' }}
                        >
                            <div className="justify-self-start rounded-full bg-[#f2f3f5] px-3 py-[7px] text-xs font-bold text-[#141518]">
                                Your PR
                            </div>
                            <SequenceArrow />
                            <StepBox number="01" title="Meaningful diff" caption="noise files skipped" />
                            <SequenceArrow />
                            <StepBox number="02" title="Split into chunks" />
                            <SequenceArrow />
                            <StepBox number="03" title="Pick perspectives" caption="only what each chunk needs" />
                        </div>

                        <FanOutConnector />

                        <div className="mb-2.5 text-center">
                            <div className="text-[11px] font-semibold tracking-[0.14em] text-[#9aa1a9]">
                                <GoldBandNumber>04</GoldBandNumber> PERSPECTIVES → <GoldBandNumber>05</GoldBandNumber>{' '}
                                BLIND SPOT · EVERY CHUNK, IN PARALLEL
                            </div>
                            <div className="mt-[3px] text-[11.5px] text-[#7d848c]">
                                e.g. contracts & security, logic & correctness, performance & reliability, or your own
                            </div>
                        </div>

                        <div className="grid grid-cols-3 gap-3">
                            {CHUNK_PICKS.map((_, i) => (
                                <ChunkCard key={i} index={i} />
                            ))}
                        </div>

                        <LaneConnector />

                        <div className="flex items-baseline justify-center gap-2.5 rounded-lg border border-[rgba(240,160,9,0.45)] bg-[#201d15] px-3 py-2.5">
                            <span className="font-mono text-[11px] tracking-[0.1em] text-[#d59220]">06</span>
                            <span className="text-[13px] font-bold">Dedupe</span>
                            <span className="text-xs text-[#cbb27e]">
                                the one pass that crosses all chunks: overlaps merged, already-raised dropped
                            </span>
                        </div>

                        <LaneConnector />

                        <div className="mb-2.5 text-center text-[11px] font-semibold tracking-[0.14em] text-[#9aa1a9]">
                            <GoldBandNumber>07</GoldBandNumber> VALIDATE · BACK IN EACH CHUNK’S LANE, IN PARALLEL
                        </div>

                        <div className="grid grid-cols-3 gap-3">
                            {CHUNK_PICKS.map((_, i) => (
                                <ValidateCard key={i} index={i} />
                            ))}
                        </div>

                        <MergeConnector />

                        <div className="flex items-center justify-center gap-2.5">
                            <div className="rounded-lg bg-[#f0a009] px-[13px] py-[9px] text-xs font-bold text-[#17130a]">
                                <span className="mr-2 font-mono text-[11px] tracking-[0.1em]">08</span>Review on your PR
                            </div>
                            <span className="text-xs text-[#9aa1a9]">one review per PR, only validated findings</span>
                        </div>

                        <div className="mt-2.5 text-center text-xs text-[#9aa1a9]">
                            Every reviewer and validator investigates your codebase, not just the diff.
                        </div>
                    </div>
                </div>
            </div>
        </LemonModal>
    )
}
