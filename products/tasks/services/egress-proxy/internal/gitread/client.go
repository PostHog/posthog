package gitread

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"regexp"
	"strings"
	"time"

	"github.com/golang-jwt/jwt/v5"

	"github.com/PostHog/posthog/products/tasks/services/egress-proxy/internal/identity"
)

var identifier = regexp.MustCompile(`^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$`)

type ClientConfig struct {
	BaseURL    string
	Region     string
	SigningKey string
	Timeout    time.Duration
	HTTPClient *http.Client
}

type Client struct {
	baseURL string
	region  string
	key     []byte
	timeout time.Duration
	http    http.Client
}

func NewClient(config ClientConfig) (*Client, error) {
	endpoint, err := url.Parse(config.BaseURL)
	if err != nil || endpoint.Scheme != "https" || endpoint.Hostname() == "" || endpoint.User != nil ||
		endpoint.Opaque != "" || endpoint.RawQuery != "" || endpoint.ForceQuery || endpoint.Fragment != "" ||
		(endpoint.Path != "" && endpoint.Path != "/") ||
		!regexp.MustCompile(`^[a-zA-Z0-9_-]{1,32}$`).MatchString(config.Region) ||
		len(config.SigningKey) < 32 || config.Timeout <= 0 {
		return nil, errors.New("invalid Git grant client configuration")
	}
	client := http.Client{}
	if config.HTTPClient != nil {
		client = *config.HTTPClient
	} else {
		transport := http.DefaultTransport.(*http.Transport).Clone()
		transport.Proxy = nil
		client.Transport = transport
	}
	client.CheckRedirect = func(_ *http.Request, _ []*http.Request) error { return http.ErrUseLastResponse }
	client.Jar = nil
	return &Client{baseURL: strings.TrimSuffix(endpoint.String(), "/"), region: config.Region,
		key: []byte(config.SigningKey), timeout: config.Timeout, http: client}, nil
}

func (c *Client) Lookup(ctx context.Context, lookup LookupRequest) (ReadGrant, error) {
	registration := lookup.Identity
	parts := strings.Split(lookup.Repository, "/")
	if !sameIdentity(registration, registration) || !time.Now().Before(registration.LeaseExpiresAt) || !identifier.MatchString(registration.RunID) ||
		!identifier.MatchString(registration.ExecutionID) || len(parts) != 2 ||
		!ownerName.MatchString(parts[0]) || !repositoryName.MatchString(parts[1]) ||
		parts[1] == "." || parts[1] == ".." || strings.HasSuffix(parts[1], ".git") ||
		lookup.Repository != strings.ToLower(lookup.Repository) {
		return ReadGrant{}, ErrDenied
	}
	ctx, cancel := context.WithTimeout(ctx, c.timeout)
	defer cancel()
	now := time.Now().Unix()
	token, err := jwt.NewWithClaims(jwt.SigningMethodHS256, jwt.MapClaims{
		"aud": "posthog:agent_egress_credentials", "sub": registration.RunID,
		"team_id": registration.TeamID, "execution_id": registration.ExecutionID,
		"region": c.region, "operation": "git_read_grant", "repository": lookup.Repository,
		"iat": now, "exp": now + 30,
	}).SignedString(c.key)
	if err != nil {
		return ReadGrant{}, ErrUnavailable
	}
	endpoint := fmt.Sprintf("%s/api/projects/%d/internal/agent_egress/runs/%s/executions/%s/git_read_grant/",
		c.baseURL, registration.TeamID, registration.RunID, registration.ExecutionID)
	request, err := http.NewRequestWithContext(ctx, http.MethodGet, endpoint, nil)
	if err != nil {
		return ReadGrant{}, ErrUnavailable
	}
	request.Header.Set("Authorization", "Bearer "+token)
	request.Header.Set("Accept", "application/json")
	response, err := c.http.Do(request)
	if err != nil {
		return ReadGrant{}, ErrUnavailable
	}
	defer response.Body.Close()
	if response.StatusCode != http.StatusOK {
		if ctx.Err() == nil {
			_, _ = io.Copy(io.Discard, io.LimitReader(response.Body, (16<<10)+1))
		}
		if response.StatusCode == http.StatusNotFound {
			return ReadGrant{}, ErrDenied
		}
		return ReadGrant{}, ErrUnavailable
	}
	body, err := io.ReadAll(io.LimitReader(response.Body, (16<<10)+1))
	if err != nil || ctx.Err() != nil || len(body) > 16<<10 {
		return ReadGrant{}, ErrUnavailable
	}
	var result struct {
		Registration struct {
			identity.Registration
			Region  string `json:"region"`
			Revoked *bool  `json:"revoked"`
		} `json:"registration"`
		Repository        string    `json:"repository"`
		Token             string    `json:"token"`
		CredentialVersion string    `json:"credential_version"`
		ExpiresAt         time.Time `json:"expires_at"`
	}
	if json.Unmarshal(body, &result) != nil || result.Registration.Revoked == nil ||
		result.Registration.Region != c.region || !sameIdentity(registration, result.Registration.Registration) ||
		result.Repository != lookup.Repository || !identifier.MatchString(result.CredentialVersion) ||
		result.Token == "" || len(result.Token) > 8192 || strings.ContainsAny(result.Token, " \t\r\n") ||
		result.Registration.LeaseExpiresAt.IsZero() || result.ExpiresAt.IsZero() {
		return ReadGrant{}, ErrUnavailable
	}
	if *result.Registration.Revoked || !time.Now().Before(result.Registration.LeaseExpiresAt) || !time.Now().Before(result.ExpiresAt) {
		return ReadGrant{}, ErrDenied
	}
	return ReadGrant{Identity: result.Registration.Registration, Repository: result.Repository,
		Token: result.Token, CredentialVersion: result.CredentialVersion, ExpiresAt: result.ExpiresAt}, nil
}
