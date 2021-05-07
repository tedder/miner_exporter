**So you want to monitor your Helium miner/validator**

# Grafana+Promethus
1. If you don't, set up Grafana and Prometheus. [Here's one guide](https://devconnected.com/how-to-setup-grafana-and-prometheus-on-linux/).
2. Monitor your server (CPU, disk IO, network usage). Conventionally this is done with [node\_exporter](https://github.com/prometheus/node_exporter).
3. Set up monitoring for the validator using [miner\_exporter](https://github.com/tedder/miner_exporter).
4. Import a dashboard. To get started, import by ID `14319`, which is the dashboard related to the miner\_exporter.
5. Help improve this document, the exporter, and the dashboard! Pull requests are welcome.

# Grafana+InfluxDB+Telegraf
1. TODO.
