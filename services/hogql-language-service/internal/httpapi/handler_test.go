package httpapi

import (
	"bytes"
	"encoding/json"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"strconv"
	"strings"
	"testing"
	"time"
	"unicode/utf16"

	"github.com/PostHog/posthog/services/hogql-language-service/internal/catalog"
	"github.com/PostHog/posthog/services/hogql-language-service/internal/completion"
	"github.com/PostHog/posthog/services/hogql-language-service/internal/ratelimit"
	"github.com/PostHog/posthog/services/hogql-language-service/internal/serviceauth"
)

func TestAutocompleteUsesOnlyRequestedTeamAndUserCatalog(t *testing.T) {
	s := newTestServer(t)
	handler := s.handler()
	putCatalogForTest(t, handler, 1, 10, "revision-one", "orders")
	putCatalogForTest(t, handler, 1, 20, "revision-two", "accounts")
	putCatalogForTest(t, handler, 2, 10, "revision-three", "invoices")

	for _, test := range []struct {
		teamID   int64
		userID   int64
		revision string
		table    string
	}{
		{teamID: 1, userID: 10, revision: "revision-one", table: "orders"},
		{teamID: 1, userID: 20, revision: "revision-two", table: "accounts"},
		{teamID: 2, userID: 10, revision: "revision-three", table: "invoices"},
	} {
		body := `{"query":"SELECT * FROM "}`
		path := scopePath(test.teamID, test.userID) + "/autocomplete"
		request := httptest.NewRequest(http.MethodPost, path, strings.NewReader(body))
		request.Header.Set("Content-Type", "application/json")
		response := httptest.NewRecorder()
		handler.ServeHTTP(response, request)
		if response.Code != http.StatusOK {
			t.Fatalf("autocomplete returned %d: %s", response.Code, response.Body.String())
		}
		if contentType := response.Header().Get("Content-Type"); contentType != "application/json; charset=utf-8" {
			t.Fatalf("unexpected Content-Type: %q", contentType)
		}
		if response.Header().Get("X-Content-Type-Options") != "nosniff" {
			t.Fatal("response is missing X-Content-Type-Options: nosniff")
		}
		if contentLength := response.Header().Get("Content-Length"); contentLength != strconv.Itoa(response.Body.Len()) {
			t.Fatalf("Content-Length = %q, response size = %d", contentLength, response.Body.Len())
		}
		var result completionResponse
		if err := json.NewDecoder(response.Body).Decode(&result); err != nil {
			t.Fatal(err)
		}
		if result.CatalogRevision != test.revision || !hasSuggestion(result.Suggestions, test.table) {
			t.Fatalf("unexpected response for team %d user %d: %#v", test.teamID, test.userID, result)
		}
		if result.PositionEncoding != completion.PositionEncodingUTF8 {
			t.Fatalf("unexpected position encoding: %q", result.PositionEncoding)
		}
		for _, otherTable := range []string{"orders", "accounts", "invoices"} {
			if otherTable != test.table && hasSuggestion(result.Suggestions, otherTable) {
				t.Fatalf("%s leaked into team %d user %d", otherTable, test.teamID, test.userID)
			}
		}
	}
}

func TestAutocompleteRequiresKnownTeamAndUser(t *testing.T) {
	s := newTestServer(t)
	for _, test := range []struct {
		path   string
		body   string
		status int
	}{
		{path: "/teams/1/users/invalid/autocomplete", body: `{"query":"SELECT "}`, status: http.StatusBadRequest},
		{path: "/teams/invalid/users/10/validate", body: `{"query":"SELECT 1"}`, status: http.StatusBadRequest},
		{path: scopePath(1, 10) + "/autocomplete", body: `{"query":"SELECT "}`, status: http.StatusNotFound},
	} {
		request := httptest.NewRequest(http.MethodPost, test.path, strings.NewReader(test.body))
		response := httptest.NewRecorder()
		s.handler().ServeHTTP(response, request)
		if response.Code != test.status {
			t.Fatalf("expected %d, got %d: %s", test.status, response.Code, response.Body.String())
		}
		if response.Header().Get("X-Content-Type-Options") != "nosniff" {
			t.Fatal("error response is missing X-Content-Type-Options: nosniff")
		}
	}
}

func TestCatalogAliasesStayWithinPublishedTeamAndUser(t *testing.T) {
	s := newTestServer(t)
	handler := s.handler()
	body := `{"revision":"aliases","catalog":{"tables":{"postgres.demo.orders":{"type":"data_warehouse","fields":{"id":{"type":"integer"}}}},"tableAliases":{"demo_postgres_orders":"postgres.demo.orders"},"properties":{}}}`
	request := httptest.NewRequest(http.MethodPut, scopePath(1, 10)+"/catalog", strings.NewReader(body))
	response := httptest.NewRecorder()
	handler.ServeHTTP(response, request)
	if response.Code != http.StatusOK {
		t.Fatalf("catalog upload returned %d: %s", response.Code, response.Body.String())
	}
	putCatalogForTest(t, handler, 1, 20, "without-aliases", "postgres.demo.orders")

	for _, test := range []struct {
		userID int64
		valid  bool
	}{
		{userID: 10, valid: true},
		{userID: 20, valid: false},
	} {
		request = httptest.NewRequest(http.MethodPost, scopePath(1, test.userID)+"/validate", strings.NewReader(`{"query":"SELECT id FROM demo_postgres_orders"}`))
		response = httptest.NewRecorder()
		handler.ServeHTTP(response, request)
		if response.Code != http.StatusOK {
			t.Fatalf("validate returned %d: %s", response.Code, response.Body.String())
		}
		var result validationResponse
		if err := json.NewDecoder(response.Body).Decode(&result); err != nil {
			t.Fatal(err)
		}
		if result.Valid != test.valid {
			t.Fatalf("user %d result = %#v", test.userID, result)
		}
	}
}

func TestCatalogRejectsInvalidAliasMaps(t *testing.T) {
	handler := newTestServer(t).handler()
	for name, aliases := range map[string]string{
		"dangling":  `{"legacy_orders":"missing"}`,
		"chain":     `{"legacy_orders":"older_orders","older_orders":"orders"}`,
		"cycle":     `{"legacy_orders":"older_orders","older_orders":"legacy_orders"}`,
		"collision": `{"orders":"events"}`,
	} {
		t.Run(name, func(t *testing.T) {
			body := `{"revision":"invalid","catalog":{"tables":{"orders":{"fields":{}},"events":{"fields":{}}},"tableAliases":` + aliases + `,"properties":{}}}`
			request := httptest.NewRequest(http.MethodPut, scopePath(1, 10)+"/catalog", strings.NewReader(body))
			response := httptest.NewRecorder()
			handler.ServeHTTP(response, request)
			if response.Code != http.StatusBadRequest || !strings.Contains(response.Body.String(), catalog.ErrInvalidAliases.Error()) {
				t.Fatalf("response = %d: %s", response.Code, response.Body.String())
			}
		})
	}
}

func TestValidateEncodesDiagnosticPositions(t *testing.T) {
	s := newTestServer(t)
	handler := s.handler()
	putCatalogForTest(t, handler, 1, 10, "revision-one", "events")
	query := "SELECT '😀', missing FROM events"
	byteStart := strings.Index(query, "missing")
	utf16Start := len(utf16.Encode([]rune(query[:byteStart])))

	for _, test := range []struct {
		encoding         string
		responseEncoding string
		start            int
	}{
		{encoding: "utf-8", responseEncoding: "utf-8", start: byteStart},
		{encoding: "utf-16", responseEncoding: "utf-16", start: utf16Start},
		{responseEncoding: "utf-16", start: utf16Start},
	} {
		body, err := json.Marshal(map[string]any{"query": query, "positionEncoding": test.encoding})
		if err != nil {
			t.Fatal(err)
		}
		request := httptest.NewRequest(http.MethodPost, scopePath(1, 10)+"/validate", bytes.NewReader(body))
		request.Header.Set("Content-Type", "application/json")
		response := httptest.NewRecorder()
		handler.ServeHTTP(response, request)
		if response.Code != http.StatusOK {
			t.Fatalf("validate returned %d: %s", response.Code, response.Body.String())
		}
		var result validationResponse
		if err := json.NewDecoder(response.Body).Decode(&result); err != nil {
			t.Fatal(err)
		}
		if string(result.PositionEncoding) != test.responseEncoding {
			t.Fatalf("position encoding = %q, want %q", result.PositionEncoding, test.responseEncoding)
		}
		if len(result.Diagnostics) != 1 {
			t.Fatalf("diagnostics = %#v", result.Diagnostics)
		}
		diagnostic := result.Diagnostics[0]
		if diagnostic.Start != test.start || diagnostic.End != test.start+len("missing") {
			t.Fatalf("%s diagnostic span = [%d,%d), want [%d,%d)", test.responseEncoding, diagnostic.Start, diagnostic.End, test.start, test.start+len("missing"))
		}
	}
}

func TestRequestLogIncludesMetadataWithoutRequestContents(t *testing.T) {
	var logs bytes.Buffer
	s := newTestServer(t)
	s.logger = slog.New(slog.NewJSONHandler(&logs, nil))
	handler := s.handler()
	putCatalogForTest(t, handler, 1, 10, "revision-one", "events")
	logs.Reset()

	request := httptest.NewRequest(http.MethodPost, scopePath(1, 10)+"/validate", strings.NewReader(`{"query":"SELECT 'do-not-log-query'"}`))
	request.Header.Set("Authorization", "Bearer do-not-log-token")
	response := httptest.NewRecorder()
	handler.ServeHTTP(response, request)
	if response.Code != http.StatusOK {
		t.Fatalf("validate returned %d: %s", response.Code, response.Body.String())
	}

	var entry map[string]any
	if err := json.Unmarshal(bytes.TrimSpace(logs.Bytes()), &entry); err != nil {
		t.Fatalf("decode request log: %v\n%s", err, logs.String())
	}
	for key, expected := range map[string]any{
		"msg":            "http_request",
		"operation":      "validate",
		"method":         http.MethodPost,
		"status_code":    float64(http.StatusOK),
		"response_bytes": float64(response.Body.Len()),
		"result":         "catalog_hit",
		"team_id":        float64(1),
		"user_id":        float64(10),
	} {
		if entry[key] != expected {
			t.Errorf("%s = %#v, want %#v", key, entry[key], expected)
		}
	}
	if duration, ok := entry["duration_ms"].(float64); !ok || duration < 0 {
		t.Errorf("duration_ms = %#v", entry["duration_ms"])
	}
	if strings.Contains(logs.String(), "do-not-log-query") || strings.Contains(logs.String(), "do-not-log-token") {
		t.Fatalf("request contents leaked into log: %s", logs.String())
	}

	logs.Reset()
	request = httptest.NewRequest(http.MethodGet, "/unknown", nil)
	response = httptest.NewRecorder()
	handler.ServeHTTP(response, request)
	if response.Code != http.StatusNotFound {
		t.Fatalf("unknown route returned %d: %s", response.Code, response.Body.String())
	}
	entry = map[string]any{}
	if err := json.Unmarshal(bytes.TrimSpace(logs.Bytes()), &entry); err != nil {
		t.Fatalf("decode unmatched request log: %v\n%s", err, logs.String())
	}
	for key, expected := range map[string]any{
		"level":       "WARN",
		"msg":         "http_request",
		"operation":   "unmatched",
		"method":      http.MethodGet,
		"status_code": float64(http.StatusNotFound),
		"result":      "error",
	} {
		if entry[key] != expected {
			t.Errorf("%s = %#v, want %#v", key, entry[key], expected)
		}
	}
}

func TestPrincipalRateLimitRunsBeforeBodyDecodeAndDoesNotCrossScopes(t *testing.T) {
	preAuthLimiter, err := ratelimit.New(ratelimit.Config{Capacity: 1, RefillPerSec: 0.001, MaxEntries: 10, IdleTTL: time.Hour})
	if err != nil {
		t.Fatal(err)
	}
	principalLimiter, err := ratelimit.New(ratelimit.Config{Capacity: 1, RefillPerSec: 0.001, MaxEntries: 10, IdleTTL: time.Hour})
	if err != nil {
		t.Fatal(err)
	}
	s := &server{
		catalogs:         catalog.NewRegistry(10, 1<<20, time.Hour),
		auth:             serviceauth.New(nil, true),
		preAuthLimiter:   preAuthLimiter,
		principalLimiter: principalLimiter,
		logger:           discardLogger(),
	}
	value := &catalog.Catalog{Tables: map[string]catalog.Table{}, Properties: map[string][]catalog.Property{}}
	for _, authorization := range []serviceauth.Authorization{{TeamID: 1, UserID: 10}, {TeamID: 1, UserID: 20}} {
		if err := s.catalogs.Put(authorization, "1", catalog.Prepare(value)); err != nil {
			t.Fatal(err)
		}
	}

	request := httptest.NewRequest(http.MethodPost, scopePath(1, 10)+"/autocomplete", strings.NewReader(`{"query":"SELECT "}`))
	response := httptest.NewRecorder()
	s.handler().ServeHTTP(response, request)
	if response.Code != http.StatusOK {
		t.Fatalf("first request returned %d: %s", response.Code, response.Body.String())
	}

	request = httptest.NewRequest(http.MethodPost, scopePath(1, 10)+"/autocomplete", strings.NewReader(`{`))
	response = httptest.NewRecorder()
	s.handler().ServeHTTP(response, request)
	if response.Code != http.StatusTooManyRequests || response.Header().Get("Retry-After") == "" {
		t.Fatalf("limited request returned %d without Retry-After: %s", response.Code, response.Body.String())
	}

	request = httptest.NewRequest(http.MethodPost, scopePath(1, 20)+"/autocomplete", strings.NewReader(`{"query":"SELECT "}`))
	response = httptest.NewRecorder()
	s.handler().ServeHTTP(response, request)
	if response.Code != http.StatusOK {
		t.Fatalf("another user inherited the rate limit: %d: %s", response.Code, response.Body.String())
	}
}

func putCatalogForTest(t *testing.T, handler http.Handler, teamID, userID int64, revision, table string) {
	t.Helper()
	body := `{"revision":"` + revision + `","catalog":{"tables":{"` + table + `":{"name":"` + table + `","type":"warehouse","fields":{}}},"properties":{}}}`
	path := scopePath(teamID, userID) + "/catalog"
	request := httptest.NewRequest(http.MethodPut, path, strings.NewReader(body))
	response := httptest.NewRecorder()
	handler.ServeHTTP(response, request)
	if response.Code != http.StatusOK {
		t.Fatalf("catalog upload returned %d: %s", response.Code, response.Body.String())
	}
}

func newTestServer(t *testing.T) *server {
	t.Helper()
	config := ratelimit.Config{Capacity: 1000, RefillPerSec: 1000, MaxEntries: 100, IdleTTL: time.Hour}
	preAuthLimiter, err := ratelimit.New(config)
	if err != nil {
		t.Fatal(err)
	}
	principalLimiter, err := ratelimit.New(config)
	if err != nil {
		t.Fatal(err)
	}
	return &server{
		catalogs:         catalog.NewRegistry(10, 1<<20, time.Hour),
		auth:             serviceauth.New(nil, true),
		preAuthLimiter:   preAuthLimiter,
		principalLimiter: principalLimiter,
		logger:           discardLogger(),
	}
}

func discardLogger() *slog.Logger {
	return slog.New(slog.NewTextHandler(io.Discard, nil))
}

func scopePath(teamID, userID int64) string {
	return "/teams/" + strconv.FormatInt(teamID, 10) + "/users/" + strconv.FormatInt(userID, 10)
}

func hasSuggestion(suggestions []completion.Suggestion, label string) bool {
	for _, suggestion := range suggestions {
		if suggestion.Label == label {
			return true
		}
	}
	return false
}
