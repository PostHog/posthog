package catalog

import "testing"

func TestIndexExactUsesUnicodeCaseFolding(t *testing.T) {
	index := newIndex([]Entry{newEntry("t", "String"), newEntry("ſ", "String")})

	entry, ok := index.Exact("s")
	if !ok || entry.Name != "ſ" {
		t.Fatalf("Exact(\"s\") = %#v, %t", entry, ok)
	}
}

func TestPreparedCatalogUsesExactTableNamesAndFoldedFieldPrefixes(t *testing.T) {
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

	if _, ok := prepared.Table("Σ"); ok {
		t.Fatal("Table(\"Σ\") matched ς")
	}
	table, ok := prepared.Table("ς")
	if !ok {
		t.Fatal("Table(\"ς\") did not find ς")
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

func TestPreparedCatalogRetainsCaseVariantTables(t *testing.T) {
	prepared := Prepare(&Catalog{
		Tables: map[string]Table{
			"Events": {Fields: map[string]Field{"upper": {Name: "upper", Type: "String"}}},
			"events": {Fields: map[string]Field{"lower": {Name: "lower", Type: "String"}}},
		},
		Properties: map[string][]Property{},
	})

	upper, upperOK := prepared.Table("Events")
	lower, lowerOK := prepared.Table("events")
	if !prepared.valid || !upperOK || !lowerOK || upper.Name != "Events" || lower.Name != "events" || prepared.TableCount() != 2 {
		t.Fatalf("prepared catalog = %#v", prepared)
	}
	prefix := prepared.Tables().Prefix("EV")
	if len(prefix) != 2 || prefix[0].Name != "Events" || prefix[1].Name != "events" {
		t.Fatalf("Prefix(\"EV\") = %#v", prefix)
	}
}
