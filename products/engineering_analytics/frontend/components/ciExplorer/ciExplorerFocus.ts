const MIN_CLICK_HEIGHT = 24

/**
 * The node a click on `element` means. A node too small to read is not what the person aimed at,
 * so the click goes to the node around it.
 */
export function clickedNodeId(element: HTMLElement): string | null {
    let target = element.closest<HTMLElement>('[data-node-id]')
    while (target && target.getBoundingClientRect().height < MIN_CLICK_HEIGHT) {
        const outer = target.parentElement?.closest<HTMLElement>('[data-node-id]')
        if (!outer) {
            break
        }
        target = outer
    }
    return target?.dataset.nodeId ?? null
}
