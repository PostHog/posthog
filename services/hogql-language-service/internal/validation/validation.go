package validation

import (
	"errors"
	"fmt"
	"iter"
	"slices"
	"sort"
	"strings"
	"time"
	"unicode/utf8"

	clickhouse "github.com/orian/clickhouse-sql-parser/parser"

	"github.com/PostHog/posthog/services/hogql-language-service/internal/analysis"
	"github.com/PostHog/posthog/services/hogql-language-service/internal/catalog"
	"github.com/PostHog/posthog/services/hogql-language-service/internal/querylimits"
	"github.com/PostHog/posthog/services/hogql-language-service/internal/textposition"
)

type Suggestion struct {
	Label    string `json:"label"`
	Distance int    `json:"distance"`
}

type Diagnostic struct {
	Code        string       `json:"code"`
	Message     string       `json:"message"`
	Start       int          `json:"start"`
	End         int          `json:"end"`
	Suggestions []Suggestion `json:"suggestions,omitempty"`
}

type Result struct {
	Valid          bool         `json:"valid"`
	Diagnostics    []Diagnostic `json:"diagnostics"`
	TableNames     []string     `json:"tableNames"`
	DurationMicros int64        `json:"durationMicros"`
}

func Validate(schema *catalog.PreparedCatalog, query string) Result {
	started := time.Now()
	document, err := analysis.Analyze(schema, query)
	if err != nil {
		code := "syntax_error"
		if errors.Is(err, querylimits.ErrQueryTooLarge) || errors.Is(err, querylimits.ErrQueryTooDeep) {
			code = "query_limit"
		}
		return result([]Diagnostic{{Code: code, Message: err.Error(), Start: 0, End: len(query)}}, nil, started)
	}

	var diagnostics []Diagnostic
	var referencedTableNames []string
	seenTableNames := map[string]bool{}
	for statement := range document.Statements() {
		for table := range statement.Tables() {
			lowerName := strings.ToLower(table.Name)
			if !seenTableNames[lowerName] {
				referencedTableNames = append(referencedTableNames, table.Name)
				seenTableNames[lowerName] = true
			}
			if !table.Known && len(diagnostics) < querylimits.MaxDiagnostics {
				diagnostics = append(diagnostics, Diagnostic{
					Code: "unknown_table", Message: fmt.Sprintf("Unknown table %q", table.Name), Start: table.Start, End: table.End,
					Suggestions: closest(table.Name, slices.Values(schema.Tables().Entries()), 5),
				})
			}
		}
		ignoredIdents := map[*clickhouse.Ident]bool{}
		statement.Walk(func(node clickhouse.Expr) bool {
			switch typed := node.(type) {
			case *clickhouse.TableIdentifier:
				ignoredIdents[typed.Database] = true
				ignoredIdents[typed.Table] = true
			case *clickhouse.CTEStmt:
				if ident, ok := typed.Expr.(*clickhouse.Ident); ok {
					ignoredIdents[ident] = true
				}
			case *clickhouse.FunctionExpr:
				ignoredIdents[typed.Name] = true
			case *clickhouse.IntervalExpr:
				ignoredIdents[typed.Unit] = true
			case *clickhouse.IntervalFrom:
				ignoredIdents[typed.Interval] = true
			case *clickhouse.SelectItem:
				ignoredIdents[typed.Alias] = true
			case *clickhouse.AliasExpr:
				if alias, ok := typed.Alias.(*clickhouse.Ident); ok {
					ignoredIdents[alias] = true
				}
			}
			return true
		})
		seen := map[string]bool{}
		statement.Walk(func(node clickhouse.Expr) bool {
			switch typed := node.(type) {
			case *clickhouse.NestedIdentifier:
				if typed.DotIdent == nil {
					return true
				}
				ignoredIdents[typed.DotIdent] = true
				bindings := statement.BindingsAt(int(node.Pos()), int(node.End()))
				if binding, ok := bindings.Relation(typed.Ident.Name); ok {
					ignoredIdents[typed.Ident] = true
					if typed.DotIdent.Name != "*" {
						validateField(&diagnostics, seen, binding, typed.DotIdent, document)
					}
				}
			case *clickhouse.Path:
				if len(typed.Fields) < 2 {
					return true
				}
				bindings := statement.BindingsAt(int(node.Pos()), int(node.End()))
				if bindings.Len() == 0 {
					return true
				}
				parts := make([]string, len(typed.Fields))
				for index, field := range typed.Fields {
					parts[index] = field.Name
				}
				if namespace, ok := bindings.PropertyNamespace(parts); ok {
					for _, field := range typed.Fields {
						ignoredIdents[field] = true
					}
					validateProperty(&diagnostics, seen, schema.Properties(namespace), typed.Fields[len(typed.Fields)-1])
					return true
				}
				if binding, ok := bindings.Relation(typed.Fields[0].Name); ok {
					for _, field := range typed.Fields {
						ignoredIdents[field] = true
					}
					validateField(&diagnostics, seen, binding, typed.Fields[1], document)
				} else {
					for _, field := range typed.Fields[1:] {
						ignoredIdents[field] = true
					}
				}
			case *clickhouse.Ident:
				if ignoredIdents[typed] || typed.Name == "*" {
					return true
				}
				bindings := statement.BindingsAt(int(node.Pos()), int(node.End()))
				if bindings.Len() > 0 {
					validateUnqualifiedField(&diagnostics, seen, bindings, typed, document)
				}
			}
			return true
		})
		if document.ProjectionLimitExceeded() {
			break
		}
	}
	if document.ProjectionLimitExceeded() && len(diagnostics) < querylimits.MaxDiagnostics {
		diagnostics = append(diagnostics, Diagnostic{
			Code: "query_limit", Message: querylimits.ErrCTEProjectionTooLarge.Error(), Start: 0, End: len(query),
		})
	}
	return result(diagnostics, referencedTableNames, started)
}

func ValidateWithEncoding(schema *catalog.PreparedCatalog, query string, encoding textposition.Encoding) (Result, error) {
	if !encoding.Valid() {
		return Result{}, fmt.Errorf("unsupported position encoding %q", encoding)
	}
	result := Validate(schema, query)
	for index := range result.Diagnostics {
		start, err := textposition.FromByteOffset(query, result.Diagnostics[index].Start, encoding)
		if err != nil {
			return Result{}, err
		}
		end, err := textposition.FromByteOffset(query, result.Diagnostics[index].End, encoding)
		if err != nil {
			return Result{}, err
		}
		result.Diagnostics[index].Start = start
		result.Diagnostics[index].End = end
	}
	return result, nil
}

func validateProperty(diagnostics *[]Diagnostic, seen map[string]bool, properties *catalog.Index, ident *clickhouse.Ident) {
	if len(*diagnostics) >= querylimits.MaxDiagnostics {
		return
	}
	if _, ok := properties.Exact(ident.Name); ok {
		return
	}
	key := fmt.Sprintf("%d:%d", ident.Pos(), ident.End())
	if seen[key] {
		return
	}
	seen[key] = true
	*diagnostics = append(*diagnostics, Diagnostic{
		Code: "unknown_property", Message: fmt.Sprintf("Unknown property %q", ident.Name), Start: int(ident.Pos()), End: int(ident.End()),
		Suggestions: closest(ident.Name, slices.Values(properties.Entries()), 5),
	})
}

func validateField(diagnostics *[]Diagnostic, seen map[string]bool, binding analysis.Relation, ident *clickhouse.Ident, document *analysis.Document) {
	if len(*diagnostics) >= querylimits.MaxDiagnostics || document.ProjectionLimitExceeded() {
		return
	}
	if _, ok := binding.Field(ident.Name); ok {
		return
	}
	if document.ProjectionLimitExceeded() {
		return
	}
	key := fmt.Sprintf("%d:%d", ident.Pos(), ident.End())
	if seen[key] {
		return
	}
	seen[key] = true
	*diagnostics = append(*diagnostics, Diagnostic{
		Code: "unknown_field", Message: fmt.Sprintf("Unknown field %q", ident.Name), Start: int(ident.Pos()), End: int(ident.End()),
		Suggestions: closest(ident.Name, binding.Fields(), 5),
	})
}

func validateUnqualifiedField(diagnostics *[]Diagnostic, seen map[string]bool, bindings analysis.Bindings, ident *clickhouse.Ident, document *analysis.Document) {
	if len(*diagnostics) >= querylimits.MaxDiagnostics || document.ProjectionLimitExceeded() {
		return
	}
	uniqueTables := map[string]analysis.Relation{}
	for _, binding := range bindings.All() {
		uniqueTables[binding.Name()] = binding
		if _, ok := binding.Field(ident.Name); ok {
			return
		}
		if document.ProjectionLimitExceeded() {
			return
		}
	}
	candidates := make([]catalog.Entry, 0)
	for _, binding := range uniqueTables {
		candidates = slices.AppendSeq(candidates, binding.Fields())
		if document.ProjectionLimitExceeded() {
			return
		}
	}
	key := fmt.Sprintf("%d:%d", ident.Pos(), ident.End())
	if seen[key] {
		return
	}
	seen[key] = true
	*diagnostics = append(*diagnostics, Diagnostic{
		Code: "unknown_field", Message: fmt.Sprintf("Unknown field %q", ident.Name), Start: int(ident.Pos()), End: int(ident.End()),
		Suggestions: closest(ident.Name, slices.Values(candidates), 5),
	})
}

func closest(input string, candidates iter.Seq[catalog.Entry], limit int) []Suggestion {
	if len(input) > querylimits.MaxSuggestionInputBytes {
		return nil
	}
	lowerInput := strings.ToLower(input)
	leftLength := utf8.RuneCountInString(lowerInput)
	threshold := min(4, max(2, leftLength/3))
	best := make([]Suggestion, 0, limit)
	workspace := levenshteinWorkspace{}
	for candidate := range candidates {
		if len(candidate.Name) > querylimits.MaxSuggestionInputBytes {
			continue
		}
		lowerCandidate := strings.ToLower(candidate.Name)
		rightLength := utf8.RuneCountInString(lowerCandidate)
		lengthDifference := max(leftLength, rightLength) - min(leftLength, rightLength)
		prefix := strings.HasPrefix(lowerCandidate, lowerInput)
		if lengthDifference > threshold && !prefix {
			continue
		}
		distance := lengthDifference
		if !prefix {
			distance = workspace.distance(lowerInput, lowerCandidate, threshold)
		}
		if distance > threshold {
			continue
		}
		suggestion := Suggestion{Label: candidate.Name, Distance: distance}
		duplicate := false
		for _, existing := range best {
			if strings.EqualFold(existing.Label, suggestion.Label) {
				duplicate = true
				break
			}
		}
		if duplicate {
			continue
		}
		if len(best) < limit {
			best = append(best, suggestion)
			sortSuggestions(best)
		} else if suggestionLess(suggestion, best[len(best)-1]) {
			best[len(best)-1] = suggestion
			sortSuggestions(best)
		}
	}
	return best
}

func sortSuggestions(suggestions []Suggestion) {
	sort.Slice(suggestions, func(left, right int) bool {
		return suggestionLess(suggestions[left], suggestions[right])
	})
}

func suggestionLess(left, right Suggestion) bool {
	if left.Distance != right.Distance {
		return left.Distance < right.Distance
	}
	return left.Label < right.Label
}

type levenshteinWorkspace struct {
	previous []int
	current  []int
}

func (w *levenshteinWorkspace) distance(left, right string, limit int) int {
	if isASCII(left) && isASCII(right) {
		for len(left) > 0 && len(right) > 0 && left[0] == right[0] {
			left = left[1:]
			right = right[1:]
		}
		for len(left) > 0 && len(right) > 0 && left[len(left)-1] == right[len(right)-1] {
			left = left[:len(left)-1]
			right = right[:len(right)-1]
		}
		return w.distanceASCII(left, right, limit)
	}
	leftRunes := []rune(left)
	rightRunes := []rune(right)
	for len(leftRunes) > 0 && len(rightRunes) > 0 && leftRunes[0] == rightRunes[0] {
		leftRunes = leftRunes[1:]
		rightRunes = rightRunes[1:]
	}
	for len(leftRunes) > 0 && len(rightRunes) > 0 && leftRunes[len(leftRunes)-1] == rightRunes[len(rightRunes)-1] {
		leftRunes = leftRunes[:len(leftRunes)-1]
		rightRunes = rightRunes[:len(rightRunes)-1]
	}
	return w.distanceRunes(leftRunes, rightRunes, limit)
}

func (w *levenshteinWorkspace) distanceASCII(left, right string, limit int) int {
	w.resize(len(right) + 1)
	for index := range len(right) + 1 {
		w.previous[index] = index
	}
	for leftIndex := range len(left) {
		w.current[0] = leftIndex + 1
		rowMinimum := w.current[0]
		for rightIndex := range len(right) {
			cost := 1
			if left[leftIndex] == right[rightIndex] {
				cost = 0
			}
			w.current[rightIndex+1] = min(w.current[rightIndex]+1, w.previous[rightIndex+1]+1, w.previous[rightIndex]+cost)
			rowMinimum = min(rowMinimum, w.current[rightIndex+1])
		}
		if rowMinimum > limit {
			return limit + 1
		}
		w.previous, w.current = w.current, w.previous
	}
	return w.previous[len(right)]
}

func (w *levenshteinWorkspace) distanceRunes(left, right []rune, limit int) int {
	w.resize(len(right) + 1)
	for index := range len(right) + 1 {
		w.previous[index] = index
	}
	for leftIndex, leftRune := range left {
		w.current[0] = leftIndex + 1
		rowMinimum := w.current[0]
		for rightIndex, rightRune := range right {
			cost := 1
			if leftRune == rightRune {
				cost = 0
			}
			w.current[rightIndex+1] = min(w.current[rightIndex]+1, w.previous[rightIndex+1]+1, w.previous[rightIndex]+cost)
			rowMinimum = min(rowMinimum, w.current[rightIndex+1])
		}
		if rowMinimum > limit {
			return limit + 1
		}
		w.previous, w.current = w.current, w.previous
	}
	return w.previous[len(right)]
}

func (w *levenshteinWorkspace) resize(size int) {
	if cap(w.previous) < size {
		w.previous = make([]int, size)
		w.current = make([]int, size)
		return
	}
	w.previous = w.previous[:size]
	w.current = w.current[:size]
}

func isASCII(value string) bool {
	for index := range len(value) {
		if value[index] >= utf8.RuneSelf {
			return false
		}
	}
	return true
}

func result(diagnostics []Diagnostic, tableNames []string, started time.Time) Result {
	if diagnostics == nil {
		diagnostics = []Diagnostic{}
	}
	if tableNames == nil {
		tableNames = []string{}
	}
	return Result{
		Valid: len(diagnostics) == 0, Diagnostics: diagnostics, TableNames: tableNames,
		DurationMicros: time.Since(started).Microseconds(),
	}
}
