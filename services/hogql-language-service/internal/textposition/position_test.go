package textposition

import "testing"

func TestToByteOffsetNormalizesUTF8CharacterBoundaries(t *testing.T) {
	value := "a😀éb"
	for _, test := range []struct {
		offset int
		expect int
	}{
		{offset: 0, expect: 0},
		{offset: 1, expect: 1},
		{offset: 2, expect: 1},
		{offset: 4, expect: 1},
		{offset: 5, expect: 5},
		{offset: 6, expect: 5},
		{offset: 7, expect: 7},
		{offset: 8, expect: 8},
	} {
		actual, err := ToByteOffset(value, test.offset, UTF8)
		if err != nil {
			t.Fatal(err)
		}
		if actual != test.expect {
			t.Errorf("ToByteOffset(%q, %d, UTF8) = %d, want %d", value, test.offset, actual, test.expect)
		}
	}
}
