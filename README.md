# prod-stack

A small 4-service web stack. First run with Docker Compose, then rebuilt on Kubernetes with plain manifests, packaged as a Helm chart, and finally deployed to AWS EC2 with Terraform. Prometheus and Grafana monitoring is available for the Compose setup (local and AWS).

    Browser -> proxy (nginx, TLS) -> frontend (nginx) -> backend (Flask) -> db (PostgreSQL 16)

## Repository layout

| Path | What it is |
|---|---|
| `backend/` | Flask app, `requirements.txt` and `Dockerfile` |
| `frontend/` | nginx config and `index.html` |
| `proxy/` | nginx config for TLS and redirect (certificates are not stored here) |
| `docker-compose.yml` | The Compose version of the stack |
| `docker-compose.aws.yml` | Compose override used on the AWS EC2 server |
| `docker-compose.monitoring.yml` | Compose override that adds Prometheus, Grafana, node-exporter and cAdvisor |
| `monitoring/` | Prometheus config, Grafana provisioning and dashboards |
| `.env.example` | Template for the database settings |
| `k8s/` | Plain Kubernetes manifests |
| `helm/prod-stack/` | The Helm chart |
| `terraform/` | Terraform for AWS: EC2, security group, IAM, CloudWatch, SNS |
| `Jenkinsfile` | Jenkins pipeline for Kubernetes (minikube) |
| `Jenkinsfile.aws` | Jenkins pipeline that deploys to the EC2 server over SSH |

## Three ways to run it

| Where | How | Started by |
|---|---|---|
| Docker Compose (laptop) | `docker compose up -d` | you, by hand |
| Kubernetes (minikube) | Helm release `prod`, namespace `prod-stack` | Jenkins job `prod-stack-pipeline` |
| AWS EC2 | `terraform apply`, then the Jenkins job `prod-stack-aws-pipeline` | you, then Jenkins |

Jenkins "Build Now" on `prod-stack-pipeline` only touches Kubernetes. Compose is always started by hand (or on AWS by the server's `user_data` script and the AWS pipeline).

## What I did

1. **Docker Compose**: backend, frontend, proxy and db, with 3 networks for isolation and a self-signed TLS certificate on the proxy.
2. **Kubernetes** (`k8s/`, namespace `prod-stack`): Deployments and ClusterIP Services for backend and frontend, the proxy exposed as NodePort (30080 and 30443), ConfigMaps for the nginx configs, Secrets for the DB credentials and the TLS certificate.
3. **StatefulSet + Headless Service** for the database, with a PVC from `volumeClaimTemplates`, so data survives pod restarts.
4. **Helm chart** (`helm/prod-stack/`): one chart installs everything. Images, replicas, NodePorts and storage size live in `values.yaml`. Secrets are not part of the chart, the chart only uses their names.
5. **Jenkins (Kubernetes)**: a pipeline (`Jenkinsfile`) builds the backend image, pushes it to Docker Hub and deploys it with `helm upgrade`.
6. **NetworkPolicy**: three ingress policies in the chart, so only proxy -> frontend -> backend -> db is allowed.
7. **AWS with Terraform** (`terraform/`): one EC2 server, security group, IAM role, CloudWatch logs, CPU alarm, dashboard and an SNS email topic. The server sets itself up with a `user_data` script.
8. **Jenkins (AWS)**: `Jenkinsfile.aws` connects to the EC2 server over SSH, pulls the latest code and rebuilds the containers.
9. **Monitoring**: Prometheus, Grafana, node-exporter and cAdvisor as a Compose override, with dashboards loaded automatically (provisioning).

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

## Monitoring (Prometheus and Grafana)

Monitoring is a separate Compose file, so the main `docker-compose.yml` stays untouched. It is only for Compose (local and AWS), not for Helm.

| Container | Job |
|---|---|
| `prometheus` | Collects metrics (3 targets: prometheus, node, cadvisor), keeps 2 days of data |
| `node-exporter` | Host CPU, memory and disk metrics |
| `cadvisor` | Per-container CPU and memory metrics |
| `grafana` | Dashboards: Node Exporter Full (ID 1860) and cAdvisor Exporter (ID 14282), loaded from `monitoring/grafana/dashboards/` |

Run it locally. Add a random Grafana password to `.env` first:

    echo "GRAFANA_ADMIN_PASSWORD=$(openssl rand -hex 12)" >> .env
    docker compose -f docker-compose.yml -f docker-compose.monitoring.yml up -d

Grafana is at `http://localhost:3000` (user `admin`) and Prometheus at `http://localhost:9090`. Both listen on `127.0.0.1` only, there is no public port, because Prometheus has no login.

On AWS the same files run on the EC2 server. Open Grafana through an SSH tunnel:

    ssh -f -N -L 3001:127.0.0.1:3000 -i ~/.ssh/id_ed25519 ubuntu@<EC2 IP>

Then open `http://localhost:3001`. The Grafana password is generated on the server and is in `~/prod-stack/.env` there.

Every monitoring container has a `mem_limit`, so the small `t3.small` server (2 GB RAM) is not squeezed.

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

Open the proxy from outside the cluster (minikube with the Docker driver needs a tunnel, keep that terminal open):

    minikube service proxy -n prod-stack --url

The tunnel prints two URLs (HTTP and HTTPS, the ports change every time). Open the HTTPS one with `https://`. Opening that port with `http://` returns `400 Bad Request`. Note that `https://localhost` (port 443) is the Compose proxy, not minikube.

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

## CI/CD with Jenkins (Kubernetes)

A Jenkins pipeline (`Jenkinsfile`, job `prod-stack-pipeline`) builds, tests and deploys the stack each time the job is started (Build Now):

| Stage | What it does |
|---|---|
| Checkout | Gets the code from GitHub |
| Build | `docker compose build` |
| Test | `docker compose config -q` and `helm lint helm/prod-stack` |
| Push | Builds the backend image and pushes it to Docker Hub as `ahmadyousaf56/prod-backend:<build number>` |
| Deploy | `helm upgrade prod` with `--set backend.image=...` and `--wait` |
| Verify | Shows the pods and the Helm history |

The job uses "Pipeline script from SCM" (this repository, branch `main`, script path `Jenkinsfile`). Jenkins reads the code from GitHub, so changes must be pushed before the job runs.

Every build gets its own image tag (the Jenkins build number). The Docker Hub login is a Jenkins credential (`dockerhub-creds`), so no password is stored in the repo.

Jenkins runs as its own `jenkins` user, so it needs access to Docker (the `docker` group) and a kubeconfig for minikube.

After `minikube start` the API port can change. Your own kubeconfig is updated automatically, but the Jenkins user's `/var/lib/jenkins/.kube/config` is not. If Deploy fails with `connection refused` on `https://127.0.0.1:<port>`, update the `server:` port in that file to match `kubectl config view --minify`.

## Deploy to AWS (Terraform)

`terraform/` creates, in `us-east-1`:

| Resource | Purpose |
|---|---|
| EC2 `t3.small` (Ubuntu, 20 GB disk) | Runs the stack with Docker Compose (`docker-compose.yml`, `docker-compose.aws.yml` and `docker-compose.monitoring.yml`) |
| Key pair | SSH login with your own `~/.ssh/id_ed25519.pub` |
| Security group | SSH (22) only from `my_ip`, HTTP (80) and HTTPS (443) from anywhere |
| IAM role, policy and instance profile | Lets the server write logs to CloudWatch |
| CloudWatch log group `/prod-stack/app`, CPU alarm and dashboard | Logs and a high-CPU alarm |
| SNS topic and email subscription | Sends the alarm to `alert_email` |

Required variables are `my_ip` (your IP in CIDR form, for example `154.208.44.0/24`) and `alert_email`. The others have defaults (`region`, `instance_type`, `public_key_path`, `repo_url`). Keep `my_ip` as a `/24` if your ISP changes your address, and check it with `curl -s https://checkip.amazonaws.com` before every apply.

    cd terraform
    terraform init
    terraform plan
    terraform apply
    terraform output

The server sets itself up with `user_data.sh` (Docker, clone of this repo, `docker compose up`). That takes about 5 to 8 minutes. During that time port 443 refuses connections, which is normal. Check with:

    ssh -i ~/.ssh/id_ed25519 ubuntu@<EC2 IP> 'cloud-init status'
    curl -k https://<EC2 IP>/api/data/

After every new apply confirm the SNS subscription email again, because the topic is new.

To stop paying, destroy everything and check that nothing is left:

    terraform destroy
    aws ec2 describe-instances --region us-east-1 --filters "Name=instance-state-name,Values=pending,running,stopping,stopped"
    aws ec2 describe-volumes --region us-east-1

## CI/CD with Jenkins (AWS)

The job `prod-stack-aws-pipeline` uses `Jenkinsfile.aws` and checks GitHub every 2 minutes (`pollSCM`).

| Stage | What it does |
|---|---|
| Checkout | Gets the code from GitHub |
| Test | Checks the configuration |
| Deploy to EC2 | SSH to the server, `git pull --ff-only`, `docker compose up -d --build` with the three Compose files, then restarts `frontend` and `proxy` |
| Verify | `curl` on `/api/data/` (fails on an HTTP error) and prints the page title |

Terraform does not tell Jenkins about the new server. After every apply give Jenkins the address and the key (the files are on the Jenkins machine, not in this repo):

- the new IP in `/var/lib/jenkins/ec2_host`
- the SSH private key at `/var/lib/jenkins/.ssh/ec2_key` (owner `jenkins`, permission `600`)
- the job's Repository URL must be this repository (`prod-stack.git`)

Keep the job disabled while no server exists, otherwise a new commit makes it try to deploy to an old address.

## NetworkPolicy

In Docker Compose the services are isolated by 3 networks. In Kubernetes every pod can reach every other pod by default, so the chart adds three ingress NetworkPolicies (`helm/prod-stack/templates/networkpolicy.yaml`):

| Policy | Applies to | Allowed in |
|---|---|---|
| `allow-backend-to-db` | `db` | only `backend`, TCP 5432 |
| `allow-frontend-to-backend` | `backend` | only `frontend`, TCP 5000 |
| `allow-proxy-to-frontend` | `frontend` | only `proxy`, TCP 80 |

The proxy has no policy because it is the entry point. The only path left is proxy -> frontend -> backend -> db.

Policies only work if the cluster's network plugin enforces them. On minikube it does (see Tested).

## Tested

- Pods db-0, backend, frontend and proxy all Running, the database PVC stays Bound and is reused.
- Deleting the db-0 pod brings back a pod with the same name, the same PVC and the same data.
- The frontend page opens over HTTPS through the proxy, and `/api/data/` returns the database version.
- `helm upgrade` to 3 backend replicas worked (Helm revision 2). `helm rollback prod 1` worked.
- Jenkins builds deployed the backend from Docker Hub with `helm upgrade`, and the pipeline finished with SUCCESS (latest Helm revision 11).
- NetworkPolicy: `proxy` to `backend` times out (blocked), while `frontend` to `backend` and `backend` to `db` (5432) work. The frontend page still returns `200 OK` over HTTPS.
- Compose: 4 containers up, `https://localhost/` shows "Welcome - Frontend Home" and `/api/data/` returns PostgreSQL 16.
- AWS: Terraform created 11 resources, the 4 containers were healthy, the page and `/api/data/` worked, and the Jenkins AWS job deployed the latest commit to the server.
- Monitoring on AWS: 8 containers up, 3 Prometheus targets `up`, both Grafana dashboards loaded without manual import.
- `terraform destroy` removed all 11 resources and no EC2 instance or volume was left.

## Not done yet

- The Kubernetes Jenkins job is started by hand (no webhook), and the Test stage only checks config (no security scan or app tests).
- Jenkins uses the full minikube kubeconfig, a ServiceAccount with limited rights would be safer. The API port in that file must be updated after a minikube restart.
- `values.yaml` still names the local image `prod-backend:v1`, Jenkins overrides it with `--set backend.image=...`.
- Monitoring is not in the Helm chart, and the Flask backend has no `/metrics` endpoint yet (only server and container metrics).
- CloudWatch container log streams and the SNS email confirmation were not checked in the last AWS test.
- Terraform state is local (no remote backend).
