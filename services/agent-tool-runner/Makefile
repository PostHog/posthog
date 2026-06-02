.PHONY: build build-runner build-fake build-image test lint fmt clean

BINARY := posthog-tool-runner
FAKE_BINARY := fake-posthog
PKG := github.com/posthog/posthog/services/agent-tool-runner
VERSION ?= $(shell git rev-parse --short HEAD 2>/dev/null || echo dev)

# `make build` produces both — the production runner customers deploy
# AND the dev fake-posthog binary used for local development.
build: build-runner build-fake

build-runner:
	mkdir -p bin
	go build -ldflags "-X main.Version=$(VERSION)" -o bin/$(BINARY) .

# fake-posthog is a developer tool — see cmd/fake-posthog/README is part
# of the parent README. Not shipped in the container image.
build-fake:
	mkdir -p bin
	go build -o bin/$(FAKE_BINARY) ./cmd/fake-posthog

build-image:
	docker build --build-arg VERSION=$(VERSION) -t posthog/posthog-tool-runner:$(VERSION) .

test:
	go test ./...

lint:
	go vet ./...
	@if [ -n "$$(gofmt -l .)" ]; then \
		echo "gofmt needs to be run on:"; \
		gofmt -l .; \
		exit 1; \
	fi

fmt:
	gofmt -w .

clean:
	rm -rf bin
