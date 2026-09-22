# Caddy with the Route53 DNS module, so the instance obtains and renews its own certificate through a DNS-01
# challenge and never listens on port 80. The distribution package has no DNS modules, hence the build.
FROM caddy:2.10.2-builder AS builder
RUN xcaddy build --with github.com/caddy-dns/route53@v1.6.2

FROM caddy:2.10.2
COPY --from=builder /usr/bin/caddy /usr/bin/caddy
