FROM node:16-alpine3.15 AS build

RUN apk update && apk add yarn curl && rm -rf /var/cache/apk/*

RUN curl -sf https://gobinaries.com/tj/node-prune | sh

COPY package.json yarn.lock ./

RUN yarn --frozen-lockfile

COPY tsconfig.json ./
COPY .swcrc ./
COPY src ./src

RUN yarn build

# RUN npm prune --production

# RUN node-prune


FROM node:16-alpine3.15

COPY package.json ./

COPY --from=build node_modules ./node_modules
COPY --from=build dist ./dist

CMD ["yarn", "start:api:prod"]
EXPOSE 3000
