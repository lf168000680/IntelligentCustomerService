FROM public.ecr.aws/docker/library/node:24-alpine as build

WORKDIR /app
COPY gui/package.json gui/package-lock.json* ./
RUN npm install --legacy-peer-deps
COPY gui/ .
RUN npm run build

FROM public.ecr.aws/docker/library/nginx:1.29-alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY gui/nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
