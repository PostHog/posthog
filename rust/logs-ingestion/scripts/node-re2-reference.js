// Writes tests/fixtures/re2-reference.json: for each pattern and flag set, whether node-re2
// compiles it, and `test` on each input. The Rust test `tests/re2_parity.rs` replays it.
//
// Run from the repository root:
//   NODE_PATH=nodejs/node_modules node rust/logs-ingestion/scripts/node-re2-reference.js
const RE2 = require('re2')
const fs = require('fs')
const path = require('path')

const patterns = [
    '', 'a', '^(GET|POST) /api', '(?=lookahead)', '(?!x)', '(?<=x)', '(?<!x)', 'HEALTHZ|token=', 'a{,5}', '{"a"',
    'a{01}', 'a{1,2}', 'a{2,}', 'a{2,1}', 'a{1000}', 'a{1001}', '(a{100}){10}', '(a{100}){11}', '((a){10}){100}',
    '((a){10}){101}', '(a{2}|b{500}){2}', '(?:a{1000})*', 'a**', 'a+*', 'a*?', 'a??', 'a???', 'a{1,2}{3}',
    'a{1,2}?', '\\<', '\\>', '[a[b]]', '[a&&b]', '[a--b]', '[--a]', '[a~~b]', '\\0', '\\12', '\\123', '\\1', '\\8',
    '\\Z', '\\z', '\\A', '\\Qa.b\\E', '\\Qa.b', '\\Q\\E*', '(?x)a b', '(?#c)', '(?i)abc', '(?-i)abc', '(?i-s:a.)',
    '(?ii)a', '(?i-)a', '(?-)a', '(?)', '(?:)', '(?U)a+', '(?m)^b$', '(?s).', '\\p{Greek}', '\\p{greek}',
    '\\p{^Greek}', '\\P{^Greek}', '\\pL', '\\PL', '\\p{L}', '\\p{Cn}', '\\p{C}', '\\p{Cs}', '\\P{Cs}', '\\p{Any}',
    '\\p{Lowercase_Letter}', '\\p{Script=Latin}', '\\p{sc=Han}', '\\p{Han}', '[\\p{L}\\d]', '[^\\pL]', '\\pN',
    '\\w', '\\W', '\\s', '\\S', '\\d', '\\D', '\\b', '\\B', '\\bword\\b', '[\\w-]', '[\\d-z]', '[a-\\d]', '[z-a]',
    '[]a]', '[^]a]', '[a-]', '[-a]', '[[:alpha:]]', '[[:^alpha:]]', '[[:word:]]', '[[:space:]]', '[[:punct:]]',
    '[[:foo:]]', '[[:alpha:]', '[a', 'a]', '(', ')', '(a', 'a)', '*', 'a|*', '(*)', '^*', '$*', '\\b+', '\\e',
    '\\y', '\\é', '\\x41', '\\x{41}', '\\x{110000}', '\\x{D800}', '\\x{}', '\\x4', '\\C', '\\uZZZZ', '\\u0041',
    '\\u00411', '\\u{1F600}', '\\cJ', '\\cj', '(?<n>a)', '(?P<n>a)', '(?P<1a>a)', '(?P<a>x)(?P<a>y)', '(?P<a-b>x)',
    '(?P=n)', '(?<n', '[(?<a]', '/path/', '\\/', '\\\\', '\\', 'a(?i)*', '(?i)k', '(?i)\\w', '(?i)\\W', '(?i)[^k]',
    '(?i)ß', '(?i)σ', 'x\ud83d', '[\ud83d]', 'a[^\ud83d]', '😀', '.', '^.$', '^...$', 'é', '(?i)É',
    '^\\s+$', '[\\s]', '\\S+@\\S+', '^/api/v[0-9]+', '/healthz', 'GET', '^$', '.*', '(a|b)*c', '(?i)ERROR|WARN',
    '\\d{3}-\\d{2}-\\d{4}', '[[:^space:]]+', '\\v', '\\a', '\\f', '\\t\\n\\r', '[\\x00-\\x7F]+', '[^\\x00-\\x7F]',
]
const inputs = [
    '', 'a', 'A', 'aa', 'ab', 'abc', 'b', 'x', 'GET /api/v1/items', 'POST /api', '/healthz', 'HEALTHZ', 'token=abc',
    'a{,5}', '{"a"', 'a{01}', '<', '>', '[]', 'a]', '&', '-', '.', '~', '\0', '\n', 'S', 'a.b', 'axb', 'α', 'π日',
    'é', 'É', '😀', '٣', 'K', 'k', 'K', 'ſ', 's', 'ß', 'ẞ', 'Σ', 'σ', 'ς', '\u000b', ' ', '\t', '\f',
    '\r\n', 'word', 'a word here', '_', '123-45-6789', 'user@example.com', '͸', '­', '', 'x\ud83d',
    '�', 'a�', 'P', '/path/', '/', '\\', 'ab\nb', ' ', 'abcabc', 'ERROR here', 'aaaa',
]
const flagSets = ['is', '']

const cases = []
for (const pattern of patterns) {
    for (const flags of flagSets) {
        let re
        try {
            re = flags ? new RE2(pattern, flags) : new RE2(pattern)
        } catch (e) {
            cases.push({ pattern, flags, compiles: false, results: [] })
            continue
        }
        cases.push({ pattern, flags, compiles: true, results: inputs.map((s) => re.test(s)) })
    }
}
const out = path.join(__dirname, '../tests/fixtures/re2-reference.json')
fs.writeFileSync(out, JSON.stringify({ inputs, cases }, null, 1) + '\n')
