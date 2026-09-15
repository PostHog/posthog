import { NODE_HEIGHT, NODE_WIDTH } from './react_flow_utils/constants'

export function setHogFlowDragImage(dataTransfer: DataTransfer, element: HTMLElement | null): void {
    if (!element || typeof dataTransfer.setDragImage !== 'function') {
        return
    }

    const preview = element.cloneNode(true) as HTMLElement
    preview.classList.remove('invisible')
    preview.style.position = 'fixed'
    preview.style.left = '0'
    preview.style.top = '0'
    preview.style.width = `${NODE_WIDTH * 1.5}px`
    preview.style.height = `${NODE_HEIGHT * 1.5}px`
    preview.style.transform = 'translate(-101%, -101%)'
    document.body.appendChild(preview)
    dataTransfer.setDragImage(preview, (NODE_WIDTH * 3) / 4, (NODE_HEIGHT * 3) / 4)
    window.setTimeout(() => preview.remove())
}
