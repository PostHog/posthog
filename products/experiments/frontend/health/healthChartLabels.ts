/** A group starts at the first position `gap` or more past the start of the group before, where its label fits. */
export function healthLabelGroups(positions: number[], gap: number): number[][] {
    const groups: number[][] = []
    positions.forEach((position, index) => {
        const group = groups.at(-1)
        if (group && position - positions[group[0]] < gap) {
            group.push(index)
        } else {
            groups.push([index])
        }
    })
    return groups
}
