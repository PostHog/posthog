package querylimits

import "errors"

const MaxQueryBytes = 64 << 10
const MaxNestingDepth = 128
const MaxSuggestionInputBytes = 128
const MaxDiagnostics = 25

var ErrQueryTooLarge = errors.New("query exceeds maximum size")
var ErrQueryTooDeep = errors.New("query exceeds maximum nesting depth")

func Validate(query string) error {
	if len(query) > MaxQueryBytes {
		return ErrQueryTooLarge
	}
	depth := 0
	var quote byte
	escaped := false
	for index := 0; index < len(query); index++ {
		character := query[index]
		if quote != 0 {
			if escaped {
				escaped = false
				continue
			}
			if character == '\\' {
				escaped = true
				continue
			}
			if character == quote {
				if index+1 < len(query) && query[index+1] == quote {
					index++
					continue
				}
				quote = 0
			}
			continue
		}
		switch character {
		case '\'', '"', '`':
			quote = character
		case '(':
			depth++
			if depth > MaxNestingDepth {
				return ErrQueryTooDeep
			}
		case ')':
			if depth > 0 {
				depth--
			}
		}
	}
	return nil
}
