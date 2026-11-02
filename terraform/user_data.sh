#!/bin/bash
set -eu
exec > /var/log/user-data.log 2>&1
export DEBIAN_FRONTEND=noninteractive

echo "[1/6] packages"
apt-get -o DPkg::Lock::Timeout=300 update
apt-get -o DPkg::Lock::Timeout=300 install -y docker.io docker-compose-v2 git openssl curl
systemctl enable --now docker
usermod -aG docker ubuntu

echo "[2/6] swap 2G"
if [ ! -f /swapfile ]; then
  fallocate -l 2G /swapfile
  chmod 600 /swapfile
  mkswap /swapfile
  swapon /swapfile
  echo "/swapfile none swap sw 0 0" >> /etc/fstab
fi

echo "[3/6] clone repo"
git clone ${repo_url} /home/ubuntu/prod-stack
cd /home/ubuntu/prod-stack

echo "[4/6] .env with random password"
DBPASS=$(openssl rand -hex 16)
printf "POSTGRES_DB=appdb\nPOSTGRES_USER=appuser\nPOSTGRES_PASSWORD=%s\n" "$DBPASS" > .env
chmod 600 .env

echo "[5/6] self-signed certificate"
TOKEN=$(curl -s -X PUT "http://169.254.169.254/latest/api/token" -H "X-aws-ec2-metadata-token-ttl-seconds: 300")
PUBIP=$(curl -s -H "X-aws-ec2-metadata-token: $TOKEN" http://169.254.169.254/latest/meta-data/public-ipv4)
mkdir -p proxy/certs
openssl req -x509 -nodes -newkey rsa:2048 -days 365 -keyout proxy/certs/server.key -out proxy/certs/server.crt -subj "/CN=$PUBIP" -addext "subjectAltName=IP:$PUBIP"
chown -R ubuntu:ubuntu /home/ubuntu/prod-stack

echo "[6/6] docker compose up"
docker compose up -d --build
touch /var/log/user-data.done
echo "user_data finished"
