# miner_exporter
Prometheus exporter for Helium miner. Using prometheus_client this code exposes metrics from the helium miner to a prometheus compatible server. 

## Requirements
This is only the exporter which still requires a prometheus server and grafana for the dashboard. Prometheus and Grafana servers can run on an external machine, the same machine as the miner, or possibly using a cloud service such as [https://grafana.com/products/cloud/](https://grafana.com/products/cloud/) this is untested.

## Installation
On the miner machine:

install python3
```
pip install prometheus_client psutil docker
```
Details on the libraries:
* [client\_python](https://github.com/prometheus/client_python)
* [psutil](https://github.com/giampaolo/psutil)
* [docker](https://pypi.org/project/docker/)

Please note this is only the exporter. Prometheus and Grafana server are required. They can be run on the same machine or external.

## Docker version
Using the docker file, you can run this with Docker or docker-compose!

### Docker
```
docker build . -tag me
docker run -v /var/run/docker.sock:/var/run/docker.sock me
```

### Docker-Compose
Using your existing docker-compose file, add the section for the exporter (below). When you're done, run it with `docker-compose up -d --build`. That's it!
```
version: "3"
services:
  validator:
    image: quay.io/team-helium/validator:latest-val-amd64
    container_name: validator
...
  miner_exporter:
    build: ./miner_exporter/
    container_name: miner_exporter
    volumes:
    - /var/run/docker.sock:/var/run/docker.sock
```
