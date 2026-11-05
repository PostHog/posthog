/** The quill sibling of `RunLogContainer`: bounds the height of a run transcript and clips it. */
export function QuillRunLogContainer({ children }: { children: React.ReactNode }): JSX.Element {
    return <div className="h-96 w-full overflow-hidden rounded-md border border-border bg-card">{children}</div>
}
