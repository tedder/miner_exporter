# So you want to monitor your Helium miner/validator

## Grafana+Promethus
1. If you don't, set up Grafana and Prometheus. [Here's one guide](https://devconnected.com/how-to-setup-grafana-and-prometheus-on-linux/).
2. Monitor your server (CPU, disk IO, network usage). Conventionally this is done with [node\_exporter](https://github.com/prometheus/node_exporter).
3. Set up monitoring for the validator using [miner\_exporter](https://github.com/tedder/miner_exporter).
4. Import a dashboard. To get started, import by ID `14319`, which is the dashboard related to the miner\_exporter.
5. Help improve this document, the exporter, and the dashboard! Pull requests are welcome.

## Grafana+InfluxDB+Telegraf
1. TODO.
2. Use [kylemanna's influx bridge](https://github.com/kylemanna/helium-validator-influx).

## Quick info in your shell
Assuming you are running your validator in docker and it is named 'validator', run the following. It will update every minute. There's one part you need to update- where it says `MINER_NAME_HERE`. Put your miner name (three-word-phrase) there. If it doesn't appear, try just a few characters, as it gets chopped off in the output.
```
watch -n60 'echo -n "miner addr:   "; docker exec validator miner peer addr | cut -d/ -f 3; echo -n "in consensus? "; docker exec validator miner info in_consensus; docker exec validator miner info p2p_status; docker exec validator miner ledger validators -v | egrep -i "MINER_NAME_HERE|owner_address"; docker exec validator miner peer book -s'
```

