;; Lua highlights

;;; Keywords

[
 "do"
 "else"
 "elseif"
 "end"
 "for"
 "function"
 "goto"
 "if"
 "in"
 "local"
 "repeat"
 "return"
 "then"
 "until"
 "while"
 (break_statement)
] @keyword

;;; Operators

[
 "and"
 "not"
 "or"
] @keyword

[
 "+"
 "-"
 "*"
 "/"
 "%"
 "^"
 "#"
 "=="
 "~="
 "<="
 ">="
 "<"
 ">"
 "="
 "&"
 "~"
 "|"
 "<<"
 ">>"
 "//"
 ".."
] @operator

;;; Punctuations

[
 ";"
 ":"
 ","
 "."
] @punctuation.delimiter

[
 "("
 ")"
 "["
 "]"
 "{"
 "}"
] @punctuation.bracket

;;; Constants

(nil) @boolean
[
 (false)
 (true)
] @boolean

(vararg_expression) @constant

((identifier) @constant
 (#match? @constant "^[A-Z][A-Z_0-9]*$"))

;;; Numbers

(number) @number

;;; Strings

(string) @string
(escape_sequence) @string.escape

;;; Comments

(comment) @comment
(hash_bang_line) @comment

;;; Tables

(field name: (identifier) @property)

(dot_index_expression field: (identifier) @property)

(table_constructor
 [
 "{"
 "}"
 ] @punctuation.bracket)

;;; Functions

(parameters (identifier) @variable)

(function_call
 name: [
 (identifier) @function
 (dot_index_expression field: (identifier) @function)
 ])

(function_declaration
 name: [
 (identifier) @function
 (dot_index_expression field: (identifier) @function)
 ])

(method_index_expression method: (identifier) @function)

;; Built-in functions
(function_call
 (identifier) @function
 (#any-of? @function
 ;; built-in functions in Lua 5.1+
 "assert" "collectgarbage" "dofile" "error" "getfenv" "getmetatable" "ipairs"
 "load" "loadfile" "loadstring" "module" "next" "pairs" "pcall" "print"
 "rawequal" "rawget" "rawset" "require" "select" "setfenv" "setmetatable"
 "tonumber" "tostring" "type" "unpack" "xpcall"))

;;; Variables

(variable_list
 attribute: (attribute
 (identifier) @attribute))

;; self reference
((identifier) @variable.special
 (#eq? @variable.special "self"))

;; Generic identifier
(identifier) @variable
