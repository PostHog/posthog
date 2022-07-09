FROM node:16-alpine3.15 AS build

COPY tsconfig.json ./
COPY package.json ./package.json
RUN yarn --frozen-lockfile

COPY src ./src
RUN yarn build

RUN npm prune --production

FROM node:16-alpine3.15

COPY package.json ./package.json

COPY --from=build node_modules ./node_modules
COPY --from=build dist ./dist

CMD ["yarn", "start:api:prod"]
EXPOSE 3000
