/**
 * Shared components for rendering cluster and trace descriptions.
 */

export interface BulletItem {
    text: string
    line_refs: string
}

export function parseBullets(bullets: string): BulletItem[] {
    try {
        const parsed = JSON.parse(bullets)
        if (Array.isArray(parsed)) {
            return parsed as BulletItem[]
        }
        return []
    } catch {
        return bullets ? [{ text: bullets, line_refs: '' }] : []
    }
}

export function BulletList({ items }: { items: BulletItem[] }): JSX.Element {
    return (
        <ul className="p-2 bg-surface-secondary rounded text-sm space-y-1 list-disc list-inside">
            {items.map((item, index) => (
                <li key={index}>{item.text}</li>
            ))}
        </ul>
    )
}

export function ClusterDescription({ description }: { description: string }): JSX.Element {
    const lines = description.split('\n').filter((line) => line.trim())
    const isBulletList = lines.length > 1 && lines.every((line) => line.trim().startsWith('- '))

    if (isBulletList) {
        return (
            <ul className="text-secondary text-sm list-disc list-inside space-y-0.5 m-0">
                {lines.map((line, index) => (
                    <li key={index}>{line.trim().slice(2)}</li>
                ))}
            </ul>
        )
    }
    return <p className="text-secondary m-0">{description}</p>
}
