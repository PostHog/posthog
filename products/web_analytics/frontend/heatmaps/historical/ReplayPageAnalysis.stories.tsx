import { Meta, StoryObj } from '@storybook/react'
import { eventWithTime } from 'posthog-js/rrweb-types'
import { useEffect } from 'react'

import { ReplayPageAnalyzer } from './replayPageAnalysis'

const events: eventWithTime[] = [
    { type: 4, timestamp: 1000, data: { href: 'https://example.com/offers', width: 1440, height: 900 } },
    {
        type: 2,
        timestamp: 1001,
        data: {
            initialOffset: { top: 0, left: 0 },
            node: {
                type: 0,
                id: 1,
                childNodes: [
                    {
                        type: 2,
                        id: 2,
                        tagName: 'html',
                        attributes: {},
                        childNodes: [
                            { type: 2, id: 3, tagName: 'head', attributes: {}, childNodes: [] },
                            {
                                type: 2,
                                id: 4,
                                tagName: 'body',
                                attributes: { style: 'margin:0' },
                                childNodes: [
                                    {
                                        type: 2,
                                        id: 5,
                                        tagName: 'main',
                                        attributes: { style: 'height:1800px;background:#eee' },
                                        childNodes: [
                                            {
                                                type: 2,
                                                id: 6,
                                                tagName: 'h1',
                                                attributes: { style: 'margin:0;height:100px' },
                                                childNodes: [{ type: 3, id: 7, textContent: 'Recorded offer' }],
                                            },
                                            {
                                                type: 2,
                                                id: 8,
                                                tagName: 'button',
                                                attributes: {
                                                    style: 'position:absolute;left:200px;top:1100px;width:200px;height:80px',
                                                },
                                                childNodes: [{ type: 3, id: 9, textContent: 'Below-fold offer' }],
                                            },
                                            {
                                                type: 2,
                                                id: 10,
                                                tagName: 'button',
                                                attributes: {
                                                    style: 'position:fixed;left:0;top:0;width:100px;height:50px',
                                                },
                                                childNodes: [{ type: 3, id: 11, textContent: 'Fixed' }],
                                            },
                                        ],
                                    },
                                ],
                            },
                        ],
                    },
                ],
            },
        },
    },
    { type: 3, timestamp: 1100, data: { source: 3, id: 1, x: 0, y: 900 } },
    { type: 3, timestamp: 1200, data: { source: 2, type: 2, id: 8, x: 250, y: 250 } },
    { type: 3, timestamp: 1300, data: { source: 2, type: 2, id: 10, x: 50, y: 25 } },
    {
        type: 3,
        timestamp: 1400,
        data: { source: 0, texts: [{ id: 7, value: 'Next offer' }], attributes: [], removes: [], adds: [] },
    },
    { type: 3, timestamp: 1500, data: { source: 2, type: 2, id: 8, x: 250, y: 250 } },
]

const snapshot = events[1]
if (snapshot.type === 2) {
    events.splice(
        3,
        0,
        { type: 4, timestamp: 1101, data: { href: 'https://example.com/offers', width: 1440, height: 900 } },
        { ...snapshot, timestamp: 1102, data: { ...snapshot.data, initialOffset: { top: 900, left: 0 } } }
    )
}

const meta: Meta = {
    title: 'Web analytics/Historical replay reconstruction',
    render: () => <p>Reconstructed recorded page</p>,
    parameters: { testOptions: { snapshotBrowsers: [] } },
}
export default meta
type Story = StoryObj

function installAnalyzer(analyzer: ReplayPageAnalyzer): void {
    window.historicalHeatmap = {
        load: () => {},
        ready: () => true,
        analyze: (input) => analyzer.analyze(input),
        render: (windowId, timestamp, signature, height) => analyzer.render(windowId, timestamp, signature, height),
        scroll: (y) => analyzer.scroll(y),
    }
}

function CaptureHarness(): JSX.Element {
    useEffect(() => {
        const analyzer = new ReplayPageAnalyzer({ 1: events })
        installAnalyzer(analyzer)
        return () => {
            analyzer.destroy()
            delete window.historicalHeatmap
        }
    }, [])
    return <p>Recorded page capture</p>
}

function DatasetHarness(): JSX.Element {
    useEffect(() => {
        let analyzer: ReplayPageAnalyzer | undefined
        const load = (event: Event): void => {
            analyzer?.destroy()
            analyzer = new ReplayPageAnalyzer((event as CustomEvent<Record<number, eventWithTime[]>>).detail)
            installAnalyzer(analyzer)
        }
        window.addEventListener('heatmap-demo-data', load)
        return () => {
            window.removeEventListener('heatmap-demo-data', load)
            analyzer?.destroy()
            delete window.historicalHeatmap
        }
    }, [])
    return (
        <div className="fixed inset-0 bg-surface-primary" data-attr="heatmap-dataset-ready">
            Load a local synthetic recording with the heatmap demo verifier.
        </div>
    )
}

export const LocalDataset: Story = { render: () => <DatasetHarness /> }

export const Capture: Story = { render: () => <CaptureHarness /> }

export const ScrollingAndLayoutChanges: Story = {
    play: async () => {
        const analyzer = new ReplayPageAnalyzer({ 1: events })
        try {
            const result = await analyzer.analyze({
                url: 'https://example.com/offers',
                date_from: 1000,
                date_to: 1500,
                viewport_width: 1440,
            })
            const clicks = result.states.flatMap((state) => state.clicks)
            if (clicks.length !== 1 || clicks[0].x !== 250 || clicks[0].y !== 1150 || result.excluded_clicks !== 1) {
                throw new Error(
                    `Incorrect document coordinates or fixed-element attribution: ${JSON.stringify(result)}`
                )
            }
            const changed = await analyzer.analyze({
                url: 'https://example.com/offers',
                date_from: 1000,
                date_to: 1600,
                viewport_width: 1440,
            })
            if (changed.states.filter((state) => state.clicks.length).length !== 2) {
                throw new Error('The changed promotion must have a separate page state')
            }
            if (new Set(changed.states.map((state) => state.visit_id)).size !== 1) {
                throw new Error('Repeated replay metadata must not count as a new page visit')
            }
            if (!(await analyzer.render(1, 1499)) || (await analyzer.scroll(900)) !== 900) {
                throw new Error('Below-fold screenshot capture must preserve recorded document coordinates')
            }
        } finally {
            analyzer.destroy()
        }
    },
}
