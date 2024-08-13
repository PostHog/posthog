FROM alpine as config-builder

RUN apk add -U yq

WORKDIR /config
COPY vector.yaml .
# evaluate with yq, basically to expand anchors (which vector doesn't support)
RUN yq -i e 'explode(.)' vector.yaml

# nightly vector to include this fix https://github.com/vectordotdev/vector/commit/dc0b4087095b4968cca0201e233919de8cff9918
FROM timberio/vector@sha256:f30cba5e4efcf554aea09a3f970fc75a140750ded0095840a47a8b9c9571100c

COPY --from=config-builder /config/vector.yaml /etc/vector/vector.yaml
