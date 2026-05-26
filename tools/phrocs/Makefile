.PHONY: build build-linux-amd64 build-linux-arm64 build-darwin-amd64 build-darwin-arm64 build-all clean deps test

BINARY_NAME=phrocs
DIST_DIR=dist

GOCMD=go
GOBUILD=$(GOCMD) build
GOCLEAN=$(GOCMD) clean
GOTEST=$(GOCMD) test
GOMOD=$(GOCMD) mod

VERSION ?= dev
COMMIT  ?= $(shell git rev-parse --short HEAD 2>/dev/null || echo unknown)
DATE    ?= $(shell date -u +%Y-%m-%dT%H:%M:%SZ)
LDFLAGS  = -ldflags '-s -w -X main.Version=$(VERSION) -X main.Commit=$(COMMIT) -X main.BuildDate=$(DATE)'

# Track every .go file plus the module manifests so `make build` becomes a
# no-op when nothing has changed. The Flox on-activate hook calls `make
# build` on every shell activation; without proper dependency tracking the
# .PHONY target would re-run `go build` from scratch each time (~3-5s per
# shell), and downstream AMI bakes wouldn't get to reuse the cached binary.
SOURCES := $(shell find . -type f -name '*.go' -not -path './$(DIST_DIR)/*') go.mod go.sum

build: $(DIST_DIR)/$(BINARY_NAME)

$(DIST_DIR)/$(BINARY_NAME): $(SOURCES) | $(DIST_DIR)
	$(GOBUILD) $(LDFLAGS) -o $@ .

$(DIST_DIR):
	mkdir -p $@

build-linux-amd64:
	CGO_ENABLED=0 GOOS=linux GOARCH=amd64 $(GOBUILD) $(LDFLAGS) -o $(DIST_DIR)/$(BINARY_NAME)-linux-amd64 .

build-linux-arm64:
	CGO_ENABLED=0 GOOS=linux GOARCH=arm64 $(GOBUILD) $(LDFLAGS) -o $(DIST_DIR)/$(BINARY_NAME)-linux-arm64 .

build-darwin-amd64:
	CGO_ENABLED=0 GOOS=darwin GOARCH=amd64 $(GOBUILD) $(LDFLAGS) -o $(DIST_DIR)/$(BINARY_NAME)-darwin-amd64 .

build-darwin-arm64:
	CGO_ENABLED=0 GOOS=darwin GOARCH=arm64 $(GOBUILD) $(LDFLAGS) -o $(DIST_DIR)/$(BINARY_NAME)-darwin-arm64 .

build-all: deps build-linux-amd64 build-linux-arm64 build-darwin-amd64 build-darwin-arm64

clean:
	$(GOCLEAN)
	rm -rf $(DIST_DIR)

deps:
	mkdir -p $(DIST_DIR)
	$(GOMOD) download

test:
	$(GOTEST) -v ./...
