FROM node:16-alpine3.15 AS build

COPY package.json /package.json
RUN yarn

COPY src ./
RUN yarn build

FROM node:16-alpine3.15

COPY package.json /package.json
RUN yarn --production=true

COPY dist ./dist

CMD ["yarn", "start:prod"]
