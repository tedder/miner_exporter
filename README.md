# miner_exporter
Prometheus exporter for Helium miner. Using prometheus_client this code exposes metrics from the helium miner to a prometheus compatible server. 

## Requirements
This is only the exporter which still requires a prometheus server and grafana for the dashboard. Prometheus and Grafana servers can run on an external machine or possibly using a cloud service such as [https://grafana.com/products/cloud/](https://grafana.com/products/cloud/)

## Installation
On the miner machine:
install python3
pip install prometheus_client [https://github.com/prometheus/client_python](https://github.com/prometheus/client_python)
pip install psutil [https://github.com/giampaolo/psutil](https://github.com/giampaolo/psutil)

Please note this is only the exporter. Prometheus and Grafana server are required. They can be run on the same machine or external.
