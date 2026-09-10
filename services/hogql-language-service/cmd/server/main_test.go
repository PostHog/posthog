package main

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strconv"
	"strings"
	"testing"
	"time"

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
		for _, otherTable := range []string{"orders", "accounts", "invoices"} {
			if otherTable != test.table && hasSuggestion(result.Suggestions, otherTable) {
				t.Fatalf("%s leaked into team %d user %d", otherTable, test.teamID, test.userID)
			}
		}
	}
}

func TestInsecureAuthenticationRequiresExplicitLoopbackOptIn(t *testing.T) {
	for _, test := range []struct {
		address    string
		configured string
		allowed    bool
		wantError  bool
	}{
		{address: "127.0.0.1:8091", configured: "", allowed: false},
		{address: "127.0.0.1:8091", configured: "1", allowed: true},
		{address: "0.0.0.0:8091", configured: "1", allowed: false, wantError: true},
	} {
		allowed, err := allowInsecureAuthentication(test.address, test.configured)
		if allowed != test.allowed || (err != nil) != test.wantError {
			t.Fatalf("address %q configured %q returned allowed=%t error=%v", test.address, test.configured, allowed, err)
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
	}
	value := &catalog.Catalog{Tables: map[string]catalog.Table{}, Properties: map[string][]catalog.Property{}}
	for _, authorization := range []serviceauth.Authorization{{TeamID: 1, UserID: 10}, {TeamID: 1, UserID: 20}} {
		if err := s.catalogs.Put(authorization, "1", value); err != nil {
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
	}
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
