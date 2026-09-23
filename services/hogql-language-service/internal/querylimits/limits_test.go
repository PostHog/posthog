package querylimits

import (
	"strings"
	"testing"
)

func TestValidateBoundsQuerySizeAndNesting(t *testing.T) {
	for _, test := range []struct {
		name  string
		query string
		err   error
	}{
		{name: "ordinary", query: "SELECT sum(amount) FROM orders"},
		{name: "parentheses in string", query: "SELECT '" + strings.Repeat("(", MaxNestingDepth+1) + "'"},
		{name: "oversized", query: strings.Repeat("a", MaxQueryBytes+1), err: ErrQueryTooLarge},
		{name: "deeply nested", query: "SELECT " + strings.Repeat("(", MaxNestingDepth+1) + "1" + strings.Repeat(")", MaxNestingDepth+1), err: ErrQueryTooDeep},
	} {
		if err := Validate(test.query); err != test.err {
			t.Fatalf("%s: got %v, want %v", test.name, err, test.err)
		}
	}
}
