package catalog

import "testing"

func TestIndexExactUsesUnicodeCaseFolding(t *testing.T) {
	index := newIndex([]Entry{newEntry("t", "String"), newEntry("ſ", "String")})

	entry, ok := index.Exact("s")
	if !ok || entry.Name != "ſ" {
		t.Fatalf("Exact(\"s\") = %#v, %t", entry, ok)
	}
}
