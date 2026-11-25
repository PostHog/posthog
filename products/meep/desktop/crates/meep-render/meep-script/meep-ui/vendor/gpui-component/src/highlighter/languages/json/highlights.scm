(comment) @comment

(string) @string
(escape_sequence) @string.escape

(number) @number

(pair key: (string) @property)

[
  (true)
  (false)
] @boolean

(null) @constant.builtin

[
  ","
  ":"
  "{"
  "}"
  "["
  "]"
] @punctuation
