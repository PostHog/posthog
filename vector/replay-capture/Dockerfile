FROM alpine as config-builder

RUN apk add -U yq

WORKDIR /config
COPY vector.yaml .
# evaluate with yq, basically to expand anchors (which vector doesn't support)
RUN yq -i e 'explode(.)' vector.yaml

FROM frankh/vector:0.41.0-patched

COPY --from=config-builder /config/vector.yaml /etc/vector/vector.yaml
