package hogqlparser

import (
	"bytes"
	"fmt"
	"sort"

	"encoding/json/jsontext"
)

// decode builds the Node tree straight from the JSON tokens. Decoding into map[string]any first costs more than the
// parse itself, because the AST has many small objects.
func decode(query string, output []byte) (*Node, error) {
	decoder := jsontext.NewDecoder(bytes.NewReader(output))
	value, err := readValue(decoder)
	if err != nil {
		return nil, fmt.Errorf("%w: decode parser output: %w", ErrInternal, err)
	}
	root, ok := value.(*Node)
	if !ok {
		return nil, fmt.Errorf("%w: parser output is not an object", ErrInternal)
	}
	if failed, _ := root.attributes["error"].(bool); failed {
		return nil, syntaxErrorFrom(query, root)
	}
	convertOffsets(root, newOffsetMap(query))
	return root, nil
}

func syntaxErrorFrom(query string, envelope *Node) *SyntaxError {
	// Error envelopes count bytes, unlike node positions, which count characters.
	syntaxError := &SyntaxError{Type: envelope.Text("type"), Message: envelope.Text("message"), End: len(query)}
	if envelope.Start >= 0 {
		syntaxError.Start = clampByteOffset(query, envelope.Start)
	}
	if envelope.End >= 0 {
		syntaxError.End = clampByteOffset(query, envelope.End)
	}
	if syntaxError.End < syntaxError.Start {
		syntaxError.Start, syntaxError.End = syntaxError.End, syntaxError.Start
	}
	return syntaxError
}

func readValue(decoder *jsontext.Decoder) (any, error) {
	token, err := decoder.ReadToken()
	if err != nil {
		return nil, err
	}
	switch token.Kind() {
	case '{':
		return readObject(decoder)
	case '[':
		return readArray(decoder)
	case '"':
		return token.String(), nil
	case '0':
		return token.Float()
	case 't', 'f':
		return token.Bool(), nil
	case 'n':
		return nil, nil
	}
	return nil, fmt.Errorf("unexpected JSON token %v", token.Kind())
}

func readArray(decoder *jsontext.Decoder) (any, error) {
	var values []any
	for decoder.PeekKind() != ']' {
		value, err := readValue(decoder)
		if err != nil {
			return nil, err
		}
		values = append(values, value)
	}
	if _, err := decoder.ReadToken(); err != nil {
		return nil, err
	}
	return values, nil
}

func readObject(decoder *jsontext.Decoder) (*Node, error) {
	node := &Node{Start: -1, End: -1, attributes: map[string]any{}, children: map[string][]*Node{}}
	for decoder.PeekKind() != '}' {
		keyToken, err := decoder.ReadToken()
		if err != nil {
			return nil, err
		}
		key := keyToken.String()
		value, err := readValue(decoder)
		if err != nil {
			return nil, err
		}
		if key == "start" || key == "end" {
			if position, ok := value.(*Node); ok && position.Kind == "" {
				if offset, ok := position.attributes["offset"].(float64); ok {
					if key == "start" {
						node.Start = int(offset)
					} else {
						node.End = int(offset)
					}
					continue
				}
			}
			if value == nil {
				continue
			}
		}
		switch typed := value.(type) {
		case *Node:
			node.addChild(key, typed)
		case []any:
			if !addArrayChildren(node, key, typed) {
				node.attributes[key] = typed
			}
		default:
			if key == "node" {
				node.Kind, _ = typed.(string)
			} else {
				node.attributes[key] = typed
			}
		}
	}
	if _, err := decoder.ReadToken(); err != nil {
		return nil, err
	}
	sort.SliceStable(node.ordered, func(left, right int) bool {
		return node.ordered[left].Start < node.ordered[right].Start
	})
	if node.Start < 0 || node.End < 0 {
		for _, child := range node.ordered {
			if child.Start < 0 {
				continue
			}
			if node.Start < 0 || child.Start < node.Start {
				node.Start = child.Start
			}
			node.End = max(node.End, child.End)
		}
	}
	return node, nil
}

// addArrayChildren registers nodes nested in arrays without losing descendants of tuple-like arrays.
func addArrayChildren(node *Node, key string, values []any) bool {
	found := false
	for _, value := range values {
		switch typed := value.(type) {
		case *Node:
			node.addChild(key, typed)
			found = true
		case []any:
			if addArrayChildren(node, key, typed) {
				found = true
			}
		}
	}
	return found
}

func convertOffsets(node *Node, offsets offsetMap) {
	if node.Start >= 0 {
		node.Start = offsets.byteOffset(node.Start)
	}
	if node.End >= 0 {
		node.End = offsets.byteOffset(node.End)
	}
	for _, child := range node.ordered {
		convertOffsets(child, offsets)
	}
}
