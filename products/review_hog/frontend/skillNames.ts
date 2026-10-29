const BUILT_IN_SKILL_LABELS: Partial<Record<string, string>> = {
    'review-hog-perspective-contracts-security': 'Security and API compatibility',
    'review-hog-perspective-logic-correctness': 'Logic and correctness',
    'review-hog-perspective-performance-reliability': 'Performance and reliability',
    'review-hog-resolution-criteria': 'Safe fixes',
    'review-hog-resolution-criteria-gaps': 'Bugs and missing functionality',
    'review-hog-resolution-criteria-small': 'Small fixes',
    'review-hog-validation-criteria': 'Issues worth fixing',
}

export function prettifySkillName(skillName: string): string {
    const builtInLabel = BUILT_IN_SKILL_LABELS[skillName]
    if (builtInLabel) {
        return builtInLabel
    }
    const cleaned = skillName
        .replace(/^review-hog-(perspective|blind-spots|validation|resolution)-/, '')
        .replace(/[-_]/g, ' ')
        .trim()
    return cleaned ? cleaned.charAt(0).toUpperCase() + cleaned.slice(1) : skillName
}
