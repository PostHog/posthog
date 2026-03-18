/// Very very scrappy function to do some syntax highlighting
export function highlightPythonSyntax(line: string): string {
    let highlighted = line.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')

    if (line.trim().startsWith('#')) {
        return `<span class="text-green-600">${highlighted}</span>`
    }

    // Split by comments to avoid highlighting inside them
    const commentIndex = line.indexOf('#')
    let beforeComment = highlighted
    let comment = ''

    if (commentIndex !== -1) {
        beforeComment = highlighted.substring(0, commentIndex)
        comment = `<span class="text-green-600">${highlighted.substring(commentIndex)}</span>`
    }

    // Apply highlighting only to the non-comment part
    let processed = beforeComment

    // Strings (avoid conflicts by being more specific)
    processed = processed.replace(
        /(^|[^a-zA-Z0-9_])(["'])((?:\\.|(?!\2)[^\\])*?)\2/g,
        '$1<span class="text-orange-400">$2$3$2</span>'
    )

    // Decorators
    processed = processed.replace(
        /(@[a-zA-Z_][a-zA-Z0-9_]*(?:\.[a-zA-Z_][a-zA-Z0-9_]*)*)/g,
        '<span class="text-yellow-400">$1</span>'
    )

    // Function definitions (def keyword + function name)
    processed = processed.replace(
        /\b(def)\s+([a-zA-Z_][a-zA-Z0-9_]*)/g,
        '<span class="text-blue-400">$1</span> <span class="text-yellow-300">$2</span>'
    )

    // Class definitions (class keyword + class name)
    processed = processed.replace(
        /\b(class)\s+([a-zA-Z_][a-zA-Z0-9_]*)/g,
        '<span class="text-blue-400">$1</span> <span class="text-green-300">$2</span>'
    )

    // Keywords (but not inside existing spans)
    processed = processed.replace(
        /\b(if|else|elif|for|while|import|from|return|try|except|finally|with|as|pass|break|continue|and|or|not|in|is|lambda|global|nonlocal|yield|async|await)\b(?![^<]*>)/g,
        '<span class="text-blue-400">$1</span>'
    )

    // Built-in functions
    processed = processed.replace(
        /\b(print|len|range|str|int|float|list|dict|set|tuple|bool|type|isinstance|hasattr|getattr|setattr|open|file|input|raw_input)\b(?![^<]*>)/g,
        '<span class="text-cyan-400">$1</span>'
    )

    // Numbers
    processed = processed.replace(/\b(\d+\.?\d*)\b(?![^<]*>)/g, '<span class="text-green-400">$1</span>')

    return processed + comment
}
