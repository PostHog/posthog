package hogqlparser

import (
	"fmt"
	"strings"
	"unicode"
	"unicode/utf8"
)

// Node is one node of the HogQL AST that posthog/hogql/ast.py defines. The parser JSON is not typed in Go, so
// callers read attributes by their Python field names, for example Children("select") on a SelectQuery.
type Node struct {
	// Kind is the Python class name, such as "SelectQuery" or "Field". It is empty for a container that the AST
	// stores as a plain object, such as the name-to-window map of SelectQuery.window_exprs.
	Kind string
	// Start and End are byte offsets into the query. A node that the parser emits without a position takes the
	// span of its children, and is -1 when it has no positioned children.
	Start, End int

	attributes map[string]any
	children   map[string][]*Node
	ordered    []*Node
}

// FieldPart is one element of a Field chain, with its own byte span in the query.
type FieldPart struct {
	Name       string
	Start, End int
}

func (n *Node) addChild(key string, child *Node) {
	n.children[key] = append(n.children[key], child)
	n.ordered = append(n.ordered, child)
}

func (n *Node) Is(kinds ...string) bool {
	return n != nil && contains(kinds, n.Kind)
}

func contains(values []string, value string) bool {
	for _, candidate := range values {
		if candidate == value {
			return true
		}
	}
	return false
}

func (n *Node) Child(key string) *Node {
	if n == nil || len(n.children[key]) == 0 {
		return nil
	}
	return n.children[key][0]
}

func (n *Node) Children(key string) []*Node {
	if n == nil {
		return nil
	}
	return n.children[key]
}

func (n *Node) Has(key string) bool {
	if n == nil {
		return false
	}
	if _, ok := n.children[key]; ok {
		return true
	}
	value, ok := n.attributes[key]
	if list, isList := value.([]any); isList {
		return len(list) > 0
	}
	return ok && value != nil
}

func (n *Node) Text(key string) string {
	if n == nil {
		return ""
	}
	value, _ := n.attributes[key].(string)
	return value
}

func (n *Node) Bool(key string) (bool, bool) {
	if n == nil {
		return false, false
	}
	value, ok := n.attributes[key].(bool)
	return value, ok
}

// Strings returns a list attribute, such as a Field chain or Lambda arguments. Integer chain elements, which
// HogQL allows for tuple positions, become their decimal text.
func (n *Node) Strings(key string) []string {
	if n == nil {
		return nil
	}
	values, _ := n.attributes[key].([]any)
	result := make([]string, 0, len(values))
	for _, value := range values {
		switch typed := value.(type) {
		case string:
			result = append(result, typed)
		case float64:
			result = append(result, fmt.Sprint(typed))
		}
	}
	return result
}

func (n *Node) Chain() []string {
	return n.Strings("chain")
}

func (n *Node) Nodes() []*Node {
	if n == nil {
		return nil
	}
	return n.ordered
}

// Walk visits the node and its descendants in source order. A false result from visit skips the children of
// that node.
func (n *Node) Walk(visit func(*Node) bool) {
	if n == nil || !visit(n) {
		return
	}
	for _, child := range n.ordered {
		child.Walk(visit)
	}
}

func (n *Node) Contains(start, end int) bool {
	return n != nil && n.Start >= 0 && n.Start <= start && end <= n.End
}

func (n *Node) Span() int {
	return n.End - n.Start
}

// FieldParts splits a Field into its chain elements with a span for each one. The AST stores one span for the
// whole chain, so the parts come from the query text. When the text does not match the chain, every part takes
// the span of the whole Field, which keeps diagnostics on the right expression.
func (n *Node) FieldParts(query string) []FieldPart {
	chain := n.Chain()
	parts := make([]FieldPart, len(chain))
	for index, name := range chain {
		parts[index] = FieldPart{Name: name, Start: n.Start, End: n.End}
	}
	if n.Start < 0 || n.End > len(query) || n.Start > n.End {
		return parts
	}
	spans, ok := scanChainSpans(query, n.Start, n.End)
	if !ok || len(spans) != len(chain) {
		return parts
	}
	for index := range parts {
		parts[index].Start, parts[index].End = spans[index][0], spans[index][1]
	}
	return parts
}

func scanChainSpans(query string, start, end int) ([][2]int, bool) {
	var spans [][2]int
	expectPart := true
	for index := start; index < end; {
		character, size := utf8.DecodeRuneInString(query[index:end])
		switch {
		case unicode.IsSpace(character):
			index += size
		case character == '.':
			if expectPart {
				return nil, false
			}
			expectPart = true
			index += size
		case !expectPart:
			return nil, false
		case character == '`' || character == '"':
			partEnd := quotedEnd(query[:end], index, byte(character))
			if partEnd < 0 {
				return nil, false
			}
			spans = append(spans, [2]int{index, partEnd})
			expectPart = false
			index = partEnd
		case character == '*':
			spans = append(spans, [2]int{index, index + size})
			expectPart = false
			index += size
		case unicode.IsLetter(character) || unicode.IsDigit(character) || character == '_' || character == '$':
			partEnd := index
			for partEnd < end {
				next, nextSize := utf8.DecodeRuneInString(query[partEnd:end])
				if !unicode.IsLetter(next) && !unicode.IsDigit(next) && next != '_' && next != '$' {
					break
				}
				partEnd += nextSize
			}
			spans = append(spans, [2]int{index, partEnd})
			expectPart = false
			index = partEnd
		default:
			return nil, false
		}
	}
	return spans, !expectPart
}

func quotedEnd(query string, start int, quote byte) int {
	for index := start + 1; index < len(query); index++ {
		switch query[index] {
		case '\\':
			index++
		case quote:
			if index+1 < len(query) && query[index+1] == quote {
				index++
				continue
			}
			return index + 1
		}
	}
	return -1
}

// offsetMap converts the parser's character offsets, which count Unicode code points like Python strings do, into
// byte offsets for Go strings.
type offsetMap struct {
	runeStarts []int
	length     int
}

func newOffsetMap(query string) offsetMap {
	for index := 0; index < len(query); index++ {
		if query[index] >= utf8.RuneSelf {
			starts := make([]int, 0, utf8.RuneCountInString(query)+1)
			for byteIndex := range query {
				starts = append(starts, byteIndex)
			}
			return offsetMap{runeStarts: append(starts, len(query)), length: len(query)}
		}
	}
	return offsetMap{length: len(query)}
}

func (m offsetMap) byteOffset(characterOffset int) int {
	if characterOffset < 0 {
		return 0
	}
	if m.runeStarts == nil {
		return min(characterOffset, m.length)
	}
	if characterOffset >= len(m.runeStarts) {
		return m.length
	}
	return m.runeStarts[characterOffset]
}

func (n *Node) Source(query string) string {
	if n == nil || n.Start < 0 || n.End > len(query) || n.Start > n.End {
		return ""
	}
	return strings.TrimSpace(query[n.Start:n.End])
}
