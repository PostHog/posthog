FROM node:16-alpine3.15 AS build

COPY package.json yarn.lock ./

RUN yarn --frozen-lockfile

COPY tsconfig.json ./
COPY .swcrc ./
COPY src ./src

RUN yarn build

RUN npm prune --production

FROM node:16-alpine3.15

COPY --from=build node_modules ./node_modules
COPY --from=build dist ./dist
COPY bin/start.sh /

CMD ["/start.sh"]
EXPOSE 3000
