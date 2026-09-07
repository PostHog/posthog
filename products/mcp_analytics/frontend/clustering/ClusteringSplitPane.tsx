import { useValues } from 'kea'
import { useRef } from 'react'

import { Resizer } from 'lib/components/Resizer/Resizer'
import { ResizerLogicProps, resizerLogic } from 'lib/components/Resizer/resizerLogic'
import { useWindowSize } from 'lib/hooks/useWindowSize'
import { cn } from 'lib/utils/css-classes'

import { panelLayoutLogic } from '~/layout/panel-layout/panelLayoutLogic'

interface ClusteringSplitPaneProps {
    /** Distinguishes the persisted widths of the two clustering views. */
    logicKey: string
    defaultWidth: number
    list: JSX.Element
    detail: JSX.Element
}

/**
 * Side-by-side list and detail, so selecting a row always changes something inside the
 * viewport. Follows the sessions tab, which uses the same Resizer split and the same
 * stacked fallback once the window is too narrow for two columns.
 */
export function ClusteringSplitPane({ logicKey, defaultWidth, list, detail }: ClusteringSplitPaneProps): JSX.Element {
    const { sidePanelWidth } = useValues(panelLayoutLogic)
    const { isWindowLessThan } = useWindowSize({ widthOffset: sidePanelWidth })
    const isVerticalLayout = isWindowLessThan('xl')

    return (
        <div
            className={cn(
                // Viewport minus the app chrome, tab strip, status row and scorecards above it,
                // so both panes scroll internally instead of the page scrolling as a whole.
                'w-full h-[calc(100vh-22rem)] min-h-[25rem] flex',
                isVerticalLayout ? 'flex-col gap-2' : 'flex-row gap-2'
            )}
        >
            {isVerticalLayout ? (
                <VerticalLayout logicKey={logicKey} list={list} detail={detail} />
            ) : (
                <HorizontalLayout logicKey={logicKey} defaultWidth={defaultWidth} list={list} detail={detail} />
            )}
        </div>
    )
}

function HorizontalLayout({
    logicKey,
    defaultWidth,
    list,
    detail,
}: Omit<ClusteringSplitPaneProps, 'logicKey'> & { logicKey: string }): JSX.Element {
    const listRef = useRef<HTMLDivElement>(null)
    const resizerLogicProps: ResizerLogicProps = {
        logicKey: `${logicKey}-horizontal`,
        containerRef: listRef,
        persistent: true,
        placement: 'right',
    }
    const { desiredSize } = useValues(resizerLogic(resizerLogicProps))

    return (
        <>
            <div
                ref={listRef}
                className="relative flex flex-col shrink-0"
                // A numeric floor rather than min-content: the tool table's intrinsic width
                // would otherwise override both the default and anything the resizer sets.
                // eslint-disable-next-line react/forbid-dom-props
                style={{ width: desiredSize ?? defaultWidth, minWidth: 280, maxWidth: '70%' }}
            >
                {list}
                <Resizer {...resizerLogicProps} visible={false} offset="0.25rem" handleClassName="rounded my-1" />
            </div>
            <div className="flex-1 min-w-0 h-full">{detail}</div>
        </>
    )
}

function VerticalLayout({
    logicKey,
    list,
    detail,
}: Pick<ClusteringSplitPaneProps, 'logicKey' | 'list' | 'detail'>): JSX.Element {
    const detailRef = useRef<HTMLDivElement>(null)
    const resizerLogicProps: ResizerLogicProps = {
        logicKey: `${logicKey}-vertical`,
        containerRef: detailRef,
        persistent: true,
        placement: 'bottom',
    }
    const { desiredSize } = useValues(resizerLogic(resizerLogicProps))

    return (
        <>
            {/* Detail on top when stacked: a list above it would push it off screen again,
                which is the failure this layout exists to fix. */}
            <div
                ref={detailRef}
                className="relative shrink-0"
                // eslint-disable-next-line react/forbid-dom-props
                style={{ height: desiredSize ?? 360, minHeight: 240 }}
            >
                {detail}
                <Resizer {...resizerLogicProps} visible={false} offset="0.25rem" handleClassName="rounded mx-1" />
            </div>
            <div className="relative flex flex-col min-h-0 flex-1">{list}</div>
        </>
    )
}
