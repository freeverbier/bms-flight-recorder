FROM node:22-alpine AS build
WORKDIR /app
COPY package.json ./
RUN npm install
COPY . .
RUN BMS_APPLIANCE=1 npm run build

FROM node:22-alpine
WORKDIR /app
ENV NODE_ENV=production PORT=3000 BMS_APPLIANCE=1
COPY --from=build /app ./
EXPOSE 3000
CMD ["node", "node_modules/vinext/dist/cli.js", "start", "--host", "0.0.0.0"]
