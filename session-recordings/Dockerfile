FROM node:16-alpine3.15 AS build

COPY tsconfig.json ./
COPY package.json ./package.json
RUN yarn

COPY src ./src
RUN yarn build

FROM node:16-alpine3.15

COPY package.json ./package.json
RUN yarn --production=true

COPY --from=build dist ./dist 

CMD ["yarn", "start:prod"]
