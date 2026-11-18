FROM golang:1.26.10-bookworm@sha256:5de7c99eb78ca5e515a4c340235d0955ec5964a5071c492c15503d7c267da473 AS build
WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY cmd ./cmd
COPY internal ./internal
RUN CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o /egress-proxy ./cmd/egress-proxy

FROM gcr.io/distroless/static-debian12:nonroot@sha256:afa5c872c891853ca7fcf1f12c3edb23f7eeef36189728842dd51042ff57f7ab
ARG COMMIT_HASH=development
LABEL org.opencontainers.image.source="https://github.com/PostHog/posthog" \
      org.opencontainers.image.revision="$COMMIT_HASH"
COPY --from=build /egress-proxy /usr/local/bin/egress-proxy
USER 65532:65532
ENTRYPOINT ["/usr/local/bin/egress-proxy"]
