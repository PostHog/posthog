package catalog

import (
	"slices"
	"sort"
	"strings"
	"unicode"
	"unicode/utf8"
)

type Field struct {
	Name string `json:"name"`
	Type string `json:"type"`
}

type Table struct {
	ID     string           `json:"id"`
	Name   string           `json:"name"`
	Type   string           `json:"type"`
	Fields map[string]Field `json:"fields"`
}

type Property struct {
	Name      string `json:"name"`
	ValueType string `json:"property_type"`
}

type Catalog struct {
	Tables     map[string]Table      `json:"tables"`
	Properties map[string][]Property `json:"properties"`
}

type Entry struct {
	Name string
	Type string
}

type Index struct {
	entries []Entry
}

type PreparedTable struct {
	Name   string
	Type   string
	Fields Index
}

type PreparedCatalog struct {
	tables         Index
	tablesByName   map[string]int
	tableValues    []PreparedTable
	properties     map[string]*Index
	valid          bool
	tableCount     int
	propertyCount  int
	estimatedBytes int64
}

func Prepare(value *Catalog) *PreparedCatalog {
	if value == nil {
		return nil
	}
	prepared := &PreparedCatalog{
		tablesByName: make(map[string]int, len(value.Tables)),
		tableValues:  make([]PreparedTable, 0, len(value.Tables)),
		properties:   make(map[string]*Index, len(value.Properties)),
		valid:        value.Tables != nil && value.Properties != nil,
		tableCount:   len(value.Tables),
	}
	fieldCount := 0
	for _, table := range value.Tables {
		fieldCount += len(table.Fields)
	}
	fieldEntries := make([]Entry, 0, fieldCount)
	tableEntries := make([]Entry, 0, len(value.Tables))
	types := map[string]string{}
	for name, table := range value.Tables {
		fieldStart := len(fieldEntries)
		for fieldName, field := range table.Fields {
			fieldEntries = append(fieldEntries, newEntry(fieldName, intern(types, field.Type)))
		}
		tableType := intern(types, table.Type)
		preparedTable := PreparedTable{Name: name, Type: tableType, Fields: newIndex(fieldEntries[fieldStart:])}
		foldedName := foldName(name)
		if _, exists := prepared.tablesByName[foldedName]; exists {
			prepared.valid = false
			continue
		}
		prepared.tablesByName[foldedName] = len(prepared.tableValues)
		prepared.tableValues = append(prepared.tableValues, preparedTable)
		tableEntries = append(tableEntries, newEntry(name, tableType))
	}
	prepared.tables = newIndex(tableEntries)
	for namespace, properties := range value.Properties {
		entries := make([]Entry, len(properties))
		for index, property := range properties {
			entries[index] = newEntry(property.Name, intern(types, property.ValueType))
		}
		index := newIndex(entries)
		prepared.properties[namespace] = &index
		prepared.propertyCount += len(entries)
	}
	prepared.estimatedBytes = prepared.estimateSize()
	return prepared
}

func (c *PreparedCatalog) Table(name string) (*PreparedTable, bool) {
	index, ok := c.tablesByName[foldName(name)]
	if !ok {
		return nil, false
	}
	return &c.tableValues[index], true
}

func (c *PreparedCatalog) Tables() *Index {
	return &c.tables
}

func (c *PreparedCatalog) Properties(namespace string) *Index {
	return c.properties[namespace]
}

func (c *PreparedCatalog) TableCount() int {
	return c.tableCount
}

func (c *PreparedCatalog) PropertyCount() int {
	return c.propertyCount
}

func (c *PreparedCatalog) EstimatedBytes() int64 {
	return c.estimatedBytes
}

func (i *Index) Exact(name string) (Entry, bool) {
	if i == nil {
		return Entry{}, false
	}
	position := sort.Search(len(i.entries), func(index int) bool {
		return compareFold(i.entries[index].Name, name) >= 0
	})
	if position == len(i.entries) || compareFold(i.entries[position].Name, name) != 0 {
		return Entry{}, false
	}
	return i.entries[position], true
}

func (i *Index) Prefix(prefix string) []Entry {
	if i == nil {
		return nil
	}
	foldedPrefix := foldName(prefix)
	start := sort.Search(len(i.entries), func(index int) bool {
		return compareFold(i.entries[index].Name, foldedPrefix) >= 0
	})
	end := len(i.entries)
	if upperBound, ok := prefixUpperBound(foldedPrefix); ok {
		end = sort.Search(len(i.entries), func(index int) bool {
			return compareFold(i.entries[index].Name, upperBound) >= 0
		})
	}
	return i.entries[start:end]
}

func (i *Index) Entries() []Entry {
	if i == nil {
		return nil
	}
	return i.entries
}

func newEntry(name, valueType string) Entry {
	return Entry{Name: name, Type: valueType}
}

func intern(values map[string]string, value string) string {
	if existing, ok := values[value]; ok {
		return existing
	}
	values[value] = value
	return value
}

func newIndex(entries []Entry) Index {
	if !slices.IsSortedFunc(entries, compareEntries) {
		slices.SortFunc(entries, compareEntries)
	}
	return Index{entries: entries}
}

func compareEntries(left, right Entry) int {
	comparison := compareFold(left.Name, right.Name)
	if comparison == 0 {
		return strings.Compare(left.Name, right.Name)
	}
	return comparison
}

func (c *PreparedCatalog) estimateSize() int64 {
	var size int64
	for _, entry := range c.tables.entries {
		size += entrySize(entry) + 64
		table := &c.tableValues[c.tablesByName[foldName(entry.Name)]]
		for _, field := range table.Fields.entries {
			size += entrySize(field)
		}
	}
	for namespace, properties := range c.properties {
		size += int64(len(namespace) + 64)
		for _, property := range properties.entries {
			size += entrySize(property)
		}
	}
	return size
}

func entrySize(entry Entry) int64 {
	return int64(len(entry.Name) + len(entry.Type) + 32)
}

func compareFold(left, right string) int {
	for len(left) > 0 && len(right) > 0 {
		leftRune, leftSize := utf8.DecodeRuneInString(left)
		rightRune, rightSize := utf8.DecodeRuneInString(right)
		leftRune = foldRune(leftRune)
		rightRune = foldRune(rightRune)
		if leftRune < rightRune {
			return -1
		}
		if leftRune > rightRune {
			return 1
		}
		left = left[leftSize:]
		right = right[rightSize:]
	}
	if len(left) > 0 {
		return 1
	}
	if len(right) > 0 {
		return -1
	}
	return 0
}

func foldName(value string) string {
	return strings.Map(foldRune, value)
}

func foldRune(value rune) rune {
	if value >= 'A' && value <= 'Z' {
		return value + 'a' - 'A'
	}
	if value >= 'a' && value <= 'z' {
		return value
	}
	canonical := value
	for candidate := unicode.SimpleFold(value); candidate != value; candidate = unicode.SimpleFold(candidate) {
		if candidate >= 'a' && candidate <= 'z' {
			return candidate
		}
		if candidate < canonical {
			canonical = candidate
		}
	}
	return canonical
}

func prefixUpperBound(prefix string) (string, bool) {
	characters := []rune(prefix)
	for index := len(characters) - 1; index >= 0; index-- {
		if characters[index] == utf8.MaxRune {
			continue
		}
		characters[index]++
		if characters[index] >= 0xD800 && characters[index] <= 0xDFFF {
			characters[index] = 0xE000
		}
		return string(characters[:index+1]), true
	}
	return "", false
}
