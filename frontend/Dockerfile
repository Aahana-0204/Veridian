FROM node:20-alpine

WORKDIR /app

COPY package.json ./
RUN npm install

# Source is volume-mounted in dev; this COPY is for production builds only
COPY . .

EXPOSE 5173

CMD ["npm", "run", "dev"]
