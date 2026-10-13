package analysis

import (
	"strings"

	clickhouse "github.com/orian/clickhouse-sql-parser/parser"
)

func IsBooleanLiteral(ident *clickhouse.Ident) bool {
	return ident.QuoteType == clickhouse.Unquoted && (strings.EqualFold(ident.Name, "TRUE") || strings.EqualFold(ident.Name, "FALSE"))
}
