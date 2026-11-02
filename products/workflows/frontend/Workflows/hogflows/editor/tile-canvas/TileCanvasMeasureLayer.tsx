import { useActions, useValues } from 'kea'
import { memo, useEffect, useLayoutEffect, useRef, useState } from 'react'

import type { HogFunctionTemplateType } from '~/types'

import { workflowLogic } from '../../../workflowLogic'
import type { HogFlow } from '../../types'
import type { NodeSize } from './tileCanvasLayout'
import { TemplateNameOf, tileCanvasLogic } from './tileCanvasLogic'
import { outgoingEdges, pathActions, VisibleNode } from './tileCanvasModel'
import { TileStackNode } from './TileStackNode'
import { TileStepNode } from './TileStepNode'

const STACK_COVER_STEPS = 4

function sizeOf(node: HTMLElement): NodeSize {
    const box = node.getBoundingClientRect()
    const anchor = node.querySelector<HTMLElement>('[data-tile-anchor]')?.getBoundingClientRect()
    return {
        width: node.offsetWidth,
        height: node.offsetHeight,
        anchor: anchor && {
            x: anchor.left - box.left + anchor.width / 2,
            y: anchor.top - box.top + anchor.height / 2,
            width: anchor.width,
            height: anchor.height,
        },
    }
}

const HIDDEN = { display: 'none' }

/** Copies stay hidden, so they cost no layout, and only the ones measured now are shown for that moment. */
function measure(container: HTMLElement, ids: ReadonlySet<string>): Record<string, NodeSize> {
    const wrappers = [...container.querySelectorAll<HTMLElement>('[data-measure-id]')].filter((wrapper) =>
        ids.has(wrapper.dataset.measureId ?? '')
    )
    wrappers.forEach((wrapper) => (wrapper.style.display = 'block'))
    const sizes: Record<string, NodeSize> = {}
    wrappers.forEach((wrapper) => {
        const node = wrapper.firstElementChild as HTMLElement | null
        if (node) {
            sizes[wrapper.dataset.measureId as string] = sizeOf(node)
        }
    })
    wrappers.forEach((wrapper) => (wrapper.style.display = HIDDEN.display))
    return sizes
}

/**
 * Everything that can change a node's size. A node whose inputs match its last measure keeps that size. Counts
 * sit in a badge over the tile, so they never change it.
 */
function sizeInputs(
    node: VisibleNode,
    workflow: HogFlow,
    templates: Record<string, HogFunctionTemplateType>
): unknown[] {
    if (node.kind === 'step') {
        return [
            node.action,
            templates,
            node.action.type === 'exit' ? workflow.exit_condition : undefined,
            outgoingEdges(workflow, node.id).length,
        ]
    }
    return [
        node.group.label,
        node.group.memberIds.length,
        templates,
        ...pathActions(workflow, node.group).slice(0, STACK_COVER_STEPS),
    ]
}

const sameInputs = (a: unknown[] | undefined, b: unknown[]): boolean =>
    !!a && a.length === b.length && a.every((value, index) => value === b[index])

/** Captions wrap differently once the web font loads, so every node is measured again then. */
function useFontsLoaded(): boolean {
    const [loaded, setLoaded] = useState(() => document.fonts?.status === 'loaded')
    useEffect(() => {
        let cancelled = false
        void document.fonts?.ready.then(() => !cancelled && setLoaded(true))
        return () => {
            cancelled = true
        }
    }, [])
    return loaded
}

const noCount = (): undefined => undefined

/** Re-renders only when the node's size inputs change, so a measured tile stays mounted untouched. */
const MeasureCopy = memo(
    function MeasureCopy({
        node,
        workflow,
        templateNameOf,
    }: {
        node: VisibleNode
        workflow: HogFlow
        templateNameOf: TemplateNameOf
        inputs: unknown[]
    }): JSX.Element {
        return (
            <div data-measure-id={node.id} className="w-max" style={HIDDEN}>
                {node.kind === 'step' ? (
                    <TileStepNode action={node.action} workflow={workflow} count={undefined} interactive={false} />
                ) : (
                    <TileStackNode
                        group={node.group}
                        workflow={workflow}
                        countOf={noCount}
                        templateNameOf={templateNameOf}
                        interactive={false}
                    />
                )}
            </div>
        )
    },
    (previous, next) => sameInputs(previous.inputs, next.inputs)
)

interface MeasuredNode {
    inputs: unknown[]
    size: NodeSize
}

export function TileCanvasMeasureLayer(): JSX.Element {
    const ref = useRef<HTMLDivElement>(null)
    const measured = useRef(new Map<string, MeasuredNode>())
    const { visibleGraph, workflow, templateNameOf } = useValues(tileCanvasLogic)
    const { hogFunctionTemplatesById } = useValues(workflowLogic)
    const { setMeasuredSizes } = useActions(tileCanvasLogic)
    const fontsLoaded = useFontsLoaded()

    const nodes = visibleGraph.nodes.map((node) => ({
        node,
        inputs: [...sizeInputs(node, workflow, hogFunctionTemplatesById), fontsLoaded],
    }))
    const changed = nodes.filter(({ node, inputs }) => !sameInputs(measured.current.get(node.id)?.inputs, inputs))

    useLayoutEffect(() => {
        const container = ref.current
        if (!container) {
            return
        }
        const sizes = measure(container, new Set(changed.map(({ node }) => node.id)))
        changed.forEach(({ node, inputs }) => {
            if (sizes[node.id]) {
                measured.current.set(node.id, { inputs, size: sizes[node.id] })
            }
        })
        setMeasuredSizes(
            Object.fromEntries(
                nodes.flatMap(({ node }) => {
                    const size = measured.current.get(node.id)?.size
                    return size ? [[node.id, size]] : []
                })
            )
        )
        // `changed` and `nodes` derive from these inputs on every render.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [visibleGraph, workflow, hogFunctionTemplatesById, fontsLoaded, setMeasuredSizes])

    return (
        <div ref={ref} aria-hidden className="pointer-events-none invisible absolute left-[-20000px] top-0">
            {nodes.map(({ node, inputs }) => (
                <MeasureCopy
                    key={node.id}
                    node={node}
                    workflow={workflow}
                    templateNameOf={templateNameOf}
                    inputs={inputs}
                />
            ))}
        </div>
    )
}
