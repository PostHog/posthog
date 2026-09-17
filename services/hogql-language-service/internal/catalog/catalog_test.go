package catalog

import "testing"

func TestIndexExactUsesUnicodeCaseFolding(t *testing.T) {
	index := newIndex([]Entry{newEntry("t", "String"), newEntry("ſ", "String")})

	entry, ok := index.Exact("s")
	if !ok || entry.Name != "ſ" {
		t.Fatalf("Exact(\"s\") = %#v, %t", entry, ok)
	}
}

func TestPreparedCatalogUsesUnicodeCaseFoldingForTableAndPrefixLookups(t *testing.T) {
	prepared := Prepare(&Catalog{
		Tables: map[string]Table{
			"ς": {
				Fields: map[string]Field{
					"ςuffix": {Name: "ςuffix", Type: "String"},
				},
			},
		},
		Properties: map[string][]Property{},
	})

	table, ok := prepared.Table("Σ")
	if !ok {
		t.Fatal("Table(\"Σ\") did not find ς")
	}
	entry, ok := table.Fields.Exact("Σuffix")
	if !ok || entry.Name != "ςuffix" {
		t.Fatalf("Exact(\"Σuffix\") = %#v, %t", entry, ok)
	}
	prefix := table.Fields.Prefix("Σ")
	if len(prefix) != 1 || prefix[0].Name != "ςuffix" {
		t.Fatalf("Prefix(\"Σ\") = %#v", prefix)
	}
}
