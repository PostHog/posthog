;; Kotlin highlights — adapted from tree-sitter-kotlin-sg (nvim-treesitter)
;; Remapped to the highlight names used by this project's registry.
;;
;; IMPORTANT: Pattern order matters. This project's highlighter keeps the
;; FIRST capture name when multiple patterns match the same range. Therefore
;; specific patterns (function, property, constant…) must appear BEFORE the
;; generic `(simple_identifier) @variable` catch-all at the end of this file.

;;; Literals (no simple_identifier conflict — safe to place early)

[
	(line_comment)
	(multiline_comment)
	(shebang_line)
] @comment

(real_literal) @number
[
	(integer_literal)
	(long_literal)
	(hex_literal)
	(bin_literal)
	(unsigned_literal)
] @number

[
	(null_literal)
	(boolean_literal)
] @boolean

(character_literal) @string

(string_literal) @string

(character_escape_seq) @string.escape

; Regex: "pattern".toRegex()
(call_expression
	(navigation_expression
		((string_literal) @string.regex)
		(navigation_suffix
			((simple_identifier) @_function
			(#eq? @_function "toRegex")))))

; Regex: Regex("pattern")
(call_expression
	((simple_identifier) @_function
	(#eq? @_function "Regex"))
	(call_suffix
		(value_arguments
			(value_argument
				(string_literal) @string.regex))))

; Regex: Regex.fromLiteral("pattern")
(call_expression
	(navigation_expression
		((simple_identifier) @_class
		(#eq? @_class "Regex"))
		(navigation_suffix
			((simple_identifier) @_function
			(#eq? @_function "fromLiteral"))))
	(call_suffix
		(value_arguments
			(value_argument
				(string_literal) @string.regex))))

;;; Keywords

(type_alias "typealias" @keyword)
[
	(class_modifier)
	(member_modifier)
	(function_modifier)
	(property_modifier)
	(platform_modifier)
	(variance_modifier)
	(parameter_modifier)
	(visibility_modifier)
	(reification_modifier)
	(inheritance_modifier)
] @keyword

[
	"val"
	"var"
	"enum"
	"class"
	"object"
	"interface"
	"companion"
	"where"
	"by"
] @keyword

("fun") @keyword

(jump_expression) @keyword

[
	"if"
	"else"
	"when"
] @keyword

[
	"for"
	"do"
	"while"
] @keyword

[
	"try"
	"catch"
	"throw"
	"finally"
] @keyword

;;; Annotations

(annotation
	"@" @attribute (use_site_target)? @attribute)
(annotation
	(user_type
		(type_identifier) @attribute))
(annotation
	(constructor_invocation
		(user_type
			(type_identifier) @attribute)))

(file_annotation
	"@" @attribute "file" @attribute ":" @attribute)
(file_annotation
	(user_type
		(type_identifier) @attribute))
(file_annotation
	(constructor_invocation
		(user_type
			(type_identifier) @attribute)))

;;; Operators & Punctuation

[
	"!"
	"!="
	"!=="
	"="
	"=="
	"==="
	">"
	">="
	"<"
	"<="
	"||"
	"&&"
	"+"
	"++"
	"+="
	"-"
	"--"
	"-="
	"*"
	"*="
	"/"
	"/="
	"%"
	"%="
	"?."
	"?:"
	"!!"
	"is"
	"in"
	"as"
	"as?"
	".."
	"->"
] @operator

[
	"(" ")"
	"[" "]"
	"{" "}"
] @punctuation.bracket

[
	"."
	","
	";"
	":"
	"::"
] @punctuation.delimiter

[
	(interpolation_identifier_start)
	(interpolation_expression_start)
	(interpolation_expression_end)
] @punctuation.special

(interpolated_identifier) @variable

;;; Types

(type_identifier) @type

;;; Package & Imports

(package_header
	"package" @keyword
	. (identifier) @type)

(import_header
	"import" @keyword)

;;; Labels

(label) @label

;;; Function definitions

(function_declaration
	. (simple_identifier) @function)

(getter
	("get") @function)
(setter
	("set") @function)

(primary_constructor) @constructor
(secondary_constructor
	("constructor") @constructor)

(constructor_invocation
	(user_type
		(type_identifier) @constructor))

(anonymous_initializer
	("init") @constructor)

;;; Function calls — must appear before the generic @variable catch-all

; function()
(call_expression
	. (simple_identifier) @function)

; object.function() or object.property.function()
(call_expression
	(navigation_expression
		(navigation_suffix
			(simple_identifier) @function) . ))

(call_expression
	. (simple_identifier) @function
    (#any-of? @function
		"arrayOf"
		"arrayOfNulls"
		"byteArrayOf"
		"shortArrayOf"
		"intArrayOf"
		"longArrayOf"
		"ubyteArrayOf"
		"ushortArrayOf"
		"uintArrayOf"
		"ulongArrayOf"
		"floatArrayOf"
		"doubleArrayOf"
		"booleanArrayOf"
		"charArrayOf"
		"emptyArray"
		"mapOf"
		"setOf"
		"listOf"
		"emptyMap"
		"emptySet"
		"emptyList"
		"mutableMapOf"
		"mutableSetOf"
		"mutableListOf"
		"print"
		"println"
		"error"
		"TODO"
		"run"
		"runCatching"
		"repeat"
		"lazy"
		"lazyOf"
		"enumValues"
		"enumValueOf"
		"assert"
		"check"
		"checkNotNull"
		"require"
		"requireNotNull"
		"with"
		"suspend"
		"synchronized"
))

;;; Identifiers — specific patterns before the catch-all

(enum_entry
	(simple_identifier) @constant)

(class_parameter
	(simple_identifier) @property)

(class_body
	(property_declaration
		(variable_declaration
			(simple_identifier) @property)))

(_
	(navigation_suffix
		(simple_identifier) @property))

(parameter
	(simple_identifier) @variable)

(parameter_with_optional_type
	(simple_identifier) @variable)

(lambda_literal
	(lambda_parameters
		(variable_declaration
			(simple_identifier) @variable)))

; `this` / `super` keywords
(this_expression) @variable.special
(super_expression) @variable.special

; `it` keyword inside lambdas
((simple_identifier) @variable.special
(#eq? @variable.special "it"))

; `field` keyword inside property getter/setter
((simple_identifier) @variable.special
(#eq? @variable.special "field"))

; `where` parsed as identifier when grammar doesn't recognise the clause
((simple_identifier) @keyword
(#eq? @keyword "where"))

; Generic identifier catch-all — MUST be last so specific patterns win
(simple_identifier) @variable
