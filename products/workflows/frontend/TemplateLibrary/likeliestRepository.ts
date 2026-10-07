import type { GitHubRepoApi } from 'products/integrations/frontend/generated/api.schemas'

export interface BrandHints {
    appUrls: string[]
    projectName: string
    organizationName: string
}

const GENERIC_WORDS = new Set([
    'www',
    'app',
    'web',
    'api',
    'dev',
    'staging',
    'preview',
    'localhost',
    'com',
    'net',
    'org',
    'the',
    'inc',
    'llc',
    'ltd',
    'gmbh',
    'corp',
    'company',
    'default',
    'project',
    'organization',
    'docs',
    'blog',
    'admin',
    'test',
    'demo',
    'beta',
    'vercel',
    'netlify',
    'github',
    'herokuapp',
    'pages',
])
const MIN_WORD_LENGTH = 3

export function likeliestRepository(repositories: GitHubRepoApi[], hints: BrandHints): GitHubRepoApi | null {
    const brandWords = brandWordsOf(hints)
    const ranked = repositories
        .filter((repository) => !repository.archived)
        .map((repository) => ({ repository, matches: coveredBrandWordCount(repository.name, brandWords) }))
        .sort(
            (a, b) =>
                b.matches - a.matches ||
                pushedAtMs(b.repository) - pushedAtMs(a.repository) ||
                a.repository.full_name.localeCompare(b.repository.full_name)
        )
    return ranked[0]?.repository ?? null
}

function brandWordsOf({ appUrls, projectName, organizationName }: BrandHints): Map<string, Set<string>> {
    const brandWords = new Map<string, Set<string>>()
    const cover = (word: string, parts: string[]): void => {
        brandWords.set(word, new Set([...(brandWords.get(word) ?? []), ...parts]))
    }
    for (const words of [...appUrls.map(hostWithoutTopLevelDomain), projectName, organizationName].map(wordsOf)) {
        words.forEach((word) => cover(word, [word]))
        if (words.length > 1) {
            cover(words.join(''), words)
        }
    }
    return brandWords
}

function coveredBrandWordCount(repositoryName: string, brandWords: Map<string, Set<string>>): number {
    const words = wordsOf(repositoryName)
    const covered = [...words, words.join('')].flatMap((word) => [...(brandWords.get(word) ?? [])])
    return new Set(covered).size
}

function wordsOf(text: string): string[] {
    return text
        .replace(/([a-z0-9])([A-Z])/g, '$1 $2')
        .toLowerCase()
        .split(/[^a-z0-9]+/)
        .filter(isBrandWord)
}

function isBrandWord(word: string): boolean {
    return word.length >= MIN_WORD_LENGTH && !GENERIC_WORDS.has(word)
}

function hostWithoutTopLevelDomain(url: string): string {
    try {
        return new URL(url.includes('://') ? url : `https://${url}`).hostname.split('.').slice(0, -1).join('.')
    } catch {
        return ''
    }
}

function pushedAtMs(repository: GitHubRepoApi): number {
    const parsed = repository.pushed_at ? Date.parse(repository.pushed_at) : 0
    return Number.isNaN(parsed) ? 0 : parsed
}
