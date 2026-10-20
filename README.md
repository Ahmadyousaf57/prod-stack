# prod-stack

A small 4-service web stack. First run with Docker Compose, then rebuilt on Kubernetes with plain manifests, and finally packaged as a Helm chart.

    Browser -> proxy (nginx, TLS) -> frontend (nginx) -> backend (Flask) -> db (PostgreSQL 16)

## Repository layout

| Path | What it is |
|---|---|
| `backend/` | Flask app, `requirements.txt` and `Dockerfile` |
| `frontend/` | nginx config and `index.html` |
| `proxy/` | nginx config for TLS and redirect (certificates are not stored here) |
| `docker-compose.yml` | The Compose version of the stack |
| `.env.example` | Template for the database settings |
| `k8s/` | Plain Kubernetes manifests |
| `helm/prod-stack/` | The Helm chart |

## What I did

1. **Docker Compose**: backend, frontend, proxy and db, with 3 networks for isolation and a self-signed TLS certificate on the proxy.
2. **Kubernetes** (`k8s/`, namespace `prod-stack`): Deployments and ClusterIP Services for backend and frontend, the proxy exposed as NodePort (30080 and 30443), ConfigMaps for the nginx configs, Secrets for the DB credentials and the TLS certificate.
3. **StatefulSet + Headless Service** for the database, with a PVC from `volumeClaimTemplates`, so data survives pod restarts.
4. **Helm chart** (`helm/prod-stack/`): one chart installs everything. Images, replicas, NodePorts and storage size live in `values.yaml`. Secrets are not part of the chart, the chart only uses their names.

## Run with Docker Compose

    cp .env.example .env
    sed -i "s/changeme/$(openssl rand -hex 7)/" .env
    mkdir -p proxy/certs
    openssl req -x509 -nodes -newkey rsa:2048 -days 365 \
      -keyout proxy/certs/server.key -out proxy/certs/server.crt \
      -subj "/CN=localhost"
    docker compose up -d --build
    curl -k https://localhost/api/data/

`.env` and `proxy/certs/` are in `.gitignore`, so they are never committed.

## Run on Kubernetes (plain manifests)

Images are built locally and loaded into minikube (the backend image is not on any registry):

    docker build -t prod-backend:v1 ./backend
    minikube image load prod-backend:v1
    minikube image load postgres:16
    minikube image load nginx:alpine

Create the namespace, the Secrets and the ConfigMaps, then apply the manifests:

    kubectl create namespace prod-stack
    kubectl config set-context --current --namespace=prod-stack
    grep '^POSTGRES_' .env > db.env
    kubectl create secret generic db-secret --from-env-file=db.env
    rm db.env
    kubectl create secret generic proxy-certs --from-file=proxy/certs/server.crt --from-file=proxy/certs/server.key
    kubectl create configmap frontend-config --from-file=frontend/nginx.conf --from-file=frontend/index.html
    kubectl create configmap proxy-config --from-file=proxy/nginx.conf
    kubectl apply -f k8s/

Open the proxy from outside the cluster (minikube with the Docker driver needs a tunnel):

    minikube service proxy -n prod-stack --url

The tunnel prints two URLs (HTTP and HTTPS, the ports change every time). Open the HTTPS one with `https://`. Opening that port with `http://` returns `400 Bad Request`.

## Run with Helm

    helm lint helm/prod-stack
    helm template prod helm/prod-stack
    helm install prod helm/prod-stack -n prod-stack --dry-run
    helm install prod helm/prod-stack -n prod-stack
    helm upgrade prod helm/prod-stack -n prod-stack --set backend.replicas=3

Create the Secrets and namespace first (next section). One release per namespace, because the Service names are fixed.

## Secrets (not stored in this repo)

Create them in the namespace before installing the chart:

    kubectl create secret generic db-secret --from-env-file=db.env -n prod-stack
    kubectl create secret generic proxy-certs --from-file=server.crt --from-file=server.key -n prod-stack

`db.env` holds the keys `POSTGRES_USER`, `POSTGRES_PASSWORD` and `POSTGRES_DB`. The certificate and key are self-signed and generated locally.

## Tested

- Pods db-0, backend, frontend and proxy all Running, the database PVC stays Bound and is reused.
- Deleting the db-0 pod brings back a pod with the same name, the same PVC and the same data.
- The frontend page opens over HTTPS through the proxy, and `/api/data/` returns the database version.
- `helm upgrade` to 3 backend replicas worked (Helm revision 2).

## Not done yet

- NetworkPolicy: the network isolation from Compose is not reproduced in Kubernetes yet.
