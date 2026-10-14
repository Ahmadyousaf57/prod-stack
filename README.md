# prod-stack: Docker Compose to Kubernetes to Helm

A small 4-service web stack. First run with Docker Compose, then rebuilt on Kubernetes with plain manifests, and finally packaged as a Helm chart.

    Browser -> proxy (nginx, TLS) -> frontend (nginx) -> backend (Flask) -> db (PostgreSQL 16)

## What I did

1. **Docker Compose**: backend, frontend, proxy and db, with 3 networks for isolation and a self-signed TLS certificate on the proxy.
2. **Kubernetes** (`k8s/`, namespace `prod-stack`): Deployments and ClusterIP Services for backend and frontend, the proxy exposed as NodePort (30080 and 30443), ConfigMaps for the nginx configs, Secrets for the DB credentials and the TLS certificate.
3. **StatefulSet + Headless Service** for the database, with a PVC from `volumeClaimTemplates`, so data survives pod restarts.
4. **Helm chart** (`helm/prod-stack/`): one chart installs everything. Images, replicas, NodePorts and storage size live in `values.yaml`. Secrets are not part of the chart, the chart only uses their names.

## Helm commands used

    helm lint helm/prod-stack
    helm template prod helm/prod-stack
    helm install prod helm/prod-stack -n prod-stack --dry-run
    helm install prod helm/prod-stack -n prod-stack
    helm upgrade prod helm/prod-stack -n prod-stack --set backend.replicas=3

## Secrets (not stored in this repo)

Create them in the namespace before installing the chart:

    kubectl create secret generic db-secret --from-env-file=db.env -n prod-stack
    kubectl create secret generic proxy-certs --from-file=server.crt --from-file=server.key -n prod-stack

`db.env` holds the keys `POSTGRES_USER`, `POSTGRES_PASSWORD` and `POSTGRES_DB`. The certificate and key are self-signed and generated locally.

## Tested

- Pods db-0, backend, frontend and proxy all Running, the database PVC stays Bound and is reused.
- The frontend page opens over HTTPS through the proxy, and `/api/data/` returns the database version.
- `helm upgrade` to 3 backend replicas worked (Helm revision 2).

## Not done yet

- NetworkPolicy: the network isolation from Compose is not reproduced in Kubernetes yet.

