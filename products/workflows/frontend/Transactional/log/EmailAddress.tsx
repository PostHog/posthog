/** Lets a long address wrap before its domain instead of mid-word. */
export function EmailAddress({
    address,
    empty = 'Unknown recipient',
}: {
    address: string
    empty?: string
}): JSX.Element {
    if (!address) {
        return <span className="text-secondary">{empty}</span>
    }
    const at = address.lastIndexOf('@')
    if (at <= 0) {
        return <span className="break-all">{address}</span>
    }
    return (
        <span className="break-words">
            {address.slice(0, at)}
            <wbr />
            {address.slice(at)}
        </span>
    )
}
