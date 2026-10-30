export function scrollTitleOpacity(scrollY: number, revealEnd: number): number {
    'worklet'
    if (revealEnd <= 0) {
        return 0
    }
    const start = Math.max(0, revealEnd - 28)
    return Math.max(0, Math.min(1, (scrollY - start) / (revealEnd - start)))
}
