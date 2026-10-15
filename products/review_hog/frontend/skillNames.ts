/** "review-hog-perspective-logic-correctness" → "Logic correctness" */
export function prettifySkillName(skillName: string): string {
    const cleaned = skillName
        .replace(/^review-hog-(perspective|blind-spots|validation|resolution)-/, '')
        .replace(/[-_]/g, ' ')
        .trim()
    return cleaned ? cleaned.charAt(0).toUpperCase() + cleaned.slice(1) : skillName
}
