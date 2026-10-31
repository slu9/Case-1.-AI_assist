FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
# Адреса попадают в rewrites на этапе сборки Next.js
ARG CAMPAIGN_API_URL
ARG CAMPAIGN_AGENT_URL
ENV CAMPAIGN_API_URL=$CAMPAIGN_API_URL CAMPAIGN_AGENT_URL=$CAMPAIGN_AGENT_URL
RUN npm run build

FROM node:22-alpine
WORKDIR /app
ENV NODE_ENV=production HOSTNAME=0.0.0.0 PORT=3000
COPY --from=build /app/.next/standalone ./
COPY --from=build /app/.next/static ./.next/static
EXPOSE 3000
CMD ["node", "server.js"]
