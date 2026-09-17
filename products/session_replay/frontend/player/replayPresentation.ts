function presentationElements(elements: Element[]): Element[] {
    const ancestors = new Set<Element>()
    for (const element of elements) {
        let current: Element | null = element
        while (current && !ancestors.has(current)) {
            ancestors.add(current)
            current = current.parentElement ?? current.ownerDocument.defaultView?.frameElement ?? null
        }
    }
    return [...ancestors]
}

export function canPresentReplayFrame(
    root: Element | null,
    replayFrame: HTMLIFrameElement | undefined,
    host: Element | null | undefined
): boolean {
    if (!root || !replayFrame || !host) {
        return false
    }
    const elements = presentationElements([root, replayFrame, host])
    return elements.every((element) => {
        if (!element.isConnected || element.ownerDocument.hidden) {
            return false
        }
        const style = element.ownerDocument.defaultView?.getComputedStyle(element)
        if (
            !style ||
            style.display === 'none' ||
            style.visibility === 'hidden' ||
            style.visibility === 'collapse' ||
            style.opacity === '0' ||
            style.contentVisibility === 'hidden'
        ) {
            return false
        }
        if (element === root || element === host || element.tagName === 'IFRAME') {
            const bounds = element.getBoundingClientRect()
            return bounds.width > 0 && bounds.height > 0
        }
        return true
    })
}

export function observeReplayPresentation(
    root: Element,
    replayFrame: HTMLIFrameElement,
    host: Element,
    onChange: () => void
): () => void {
    const elements = presentationElements([root, replayFrame, host])
    const resize = new ResizeObserver(onChange)
    const mutation = new MutationObserver(onChange)
    for (const element of elements) {
        resize.observe(element)
        mutation.observe(element, { attributes: true, attributeFilter: ['class', 'style', 'hidden'] })
    }
    const documents = new Set(elements.map((element) => element.ownerDocument))
    for (const document of documents) {
        document.addEventListener('visibilitychange', onChange)
    }
    return () => {
        resize.disconnect()
        mutation.disconnect()
        for (const document of documents) {
            document.removeEventListener('visibilitychange', onChange)
        }
    }
}
