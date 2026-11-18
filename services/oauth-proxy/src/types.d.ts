declare module '*.html' {
    const content: string
    export default content
}

declare module '*.woff2' {
    const content: ArrayBuffer
    export default content
}
