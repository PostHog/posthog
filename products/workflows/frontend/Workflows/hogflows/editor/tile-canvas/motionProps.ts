import type { NodeMotion } from './tileCanvasModel'

export function motionProps(motion: NodeMotion | undefined): { className?: string; style?: React.CSSProperties } {
    if (!motion) {
        return {}
    }
    return {
        className: `TileCanvas__motion--${motion.type}`,
        style: { '--tile-canvas-dx': `${motion.dx}px`, '--tile-canvas-dy': `${motion.dy}px` } as React.CSSProperties,
    }
}
