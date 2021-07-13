#!/usr/bin/env python3

# external packages
import prometheus_client
import psutil
import docker
import requests
import dateutil.parser

# I just copied the python script from https://github.com/andrewboudreau/miner_httpclient into the folder for easy testing.
from miner_client import MinerClient

# internal packages
import datetime
import time
import subprocess
import sys
import os
import re
import logging

# remember, levels: debug, info, warning, error, critical. there is no trace.
logging.basicConfig(format="%(filename)s:%(funcName)s:%(lineno)d:%(levelname)s\t%(message)s", level=logging.WARNING)
log = logging.getLogger(__name__)
log.setLevel(logging.INFO)

# time to sleep between scrapes
UPDATE_PERIOD = int(os.environ.get('UPDATE_PERIOD', 30))
VALIDATOR_CONTAINER_NAME = os.environ.get('VALIDATOR_CONTAINER_NAME', 'validator')
# for testnet, https://testnet-api.helium.wtf/v1
API_BASE_URL = os.environ.get('API_BASE_URL', 'https://api.helium.io/v1')

# Gather the ledger penalities for all, instead of just "this" validator. When in this
# mode all validators from `miner validator ledger` with a penalty >0.0 will be included.
# The >0 constraint is just to keep data and traffic smaller.
ALL_PENALTIES = os.environ.get('ALL_PENALTIES', 0)

# use the RPC calls where available. This means you have your RPC port open.
# Once all of the exec calls are replaced we can enable this by default.
ENABLE_RPC = os.environ.get('ENABLE_RPC', 0)

# prometheus exporter types Gauge,Counter,Summary,Histogram,Info and Enum
SCRAPE_TIME = prometheus_client.Summary('validator_scrape_time', 'Time spent collecting miner data')
VALIDATOR_DISK_USAGE = prometheus_client.Gauge('validator_disk_usage_bytes',
                                       'Disk used by validator directory/volume',
                                       ['validator_name'])
SYSTEM_USAGE = prometheus_client.Gauge('system_usage',
                                       'Hold current system resource usage',
                                       ['resource_type','validator_name'])
CHAIN_STATS = prometheus_client.Gauge('chain_stats',
                              'Stats about the global chain', ['resource_type'])
VAL = prometheus_client.Gauge('validator_height',
                              "Height of the validator's blockchain",
                              ['resource_type','validator_name'])
INCON = prometheus_client.Gauge('validator_inconsensus',
                              'Is validator currently in consensus group',
                              ['validator_name'])
BLOCKAGE = prometheus_client.Gauge('validator_block_age',
                              'Age of the current block',
                             ['resource_type','validator_name'])
HBBFT_PERF = prometheus_client.Gauge('validator_hbbft_perf',
                              'HBBFT performance metrics from perf, only applies when in CG',
                             ['resource_type','subtype','validator_name'])
CONNECTIONS = prometheus_client.Gauge('validator_connections',
                              'Number of libp2p connections ',
                             ['resource_type','validator_name'])
SESSIONS = prometheus_client.Gauge('validator_sessions',
                              'Number of libp2p sessions',
                             ['resource_type','validator_name'])
LEDGER_PENALTY = prometheus_client.Gauge('validator_ledger',
                              'Validator performance metrics ',
                             ['resource_type', 'subtype','validator_name'])
VALIDATOR_VERSION = prometheus_client.Info('validator_version',
                              'Version number of the miner container',['validator_name'])
BALANCE = prometheus_client.Gauge('validator_api_balance',
                              'Balance of the validator owner account',['validator_name'])
UPTIME = prometheus_client.Gauge('validator_container_uptime',
                              'Time container has been at a given state',
                              ['state_type','validator_name'])

# create a client for the miner's json rpc interface
jsonRpcClient = MinerClient()

def try_float(v):
  if re.match(r"^\-?[\d\.]+$", v):
    return float(v)
  return v

# Decorate function with metric.
@SCRAPE_TIME.time()
def stats():
  miner_name = jsonRpcClient.info_name()
  
  try:
    dc = docker.DockerClient()

    # Try to find by specific name first
    docker_container = dc.containers.get(VALIDATOR_CONTAINER_NAME)
  except docker.errors.NotFound as ex:
    log.error(f"docker failed while bootstrapping. Not exporting anything. Error: {ex}")
    return  
  
  # collect total cpu and memory usage. Might want to consider just the docker
  # container with something like cadvisor instead
  SYSTEM_USAGE.labels('CPU', miner_name).set(psutil.cpu_percent())
  SYSTEM_USAGE.labels('Memory', miner_name).set(psutil.virtual_memory()[2])

  collect_container_run_time(docker_container, miner_name)
  collect_hbbft_performance(docker_container, miner_name)

  collect_block_age(miner_name)
  collect_miner_height(miner_name)
  collect_in_consensus(miner_name)
  collect_ledger_validators(miner_name)
  collect_peer_book(miner_name)
  collect_balance(miner_name) 

def safe_get_json(url):
  try:
    ret = requests.get(url)
    if not ret.status_code == requests.codes.ok:
      log.error(f"bad status code ({ret.status_code}) from url: {url}")
      return
    retj = ret.json()
    return retj
    
  except (requests.exceptions.SSLError, requests.exceptions.ConnectionError) as ex:
    log.error(f"error fetching {url}: {ex}")
    return
    
def collect_container_run_time(docker_container, miner_name):
  attrs = docker_container.attrs

  # examples and other things we could track:
  # "Created": "2021-05-18T22:11:48.962678927Z",
  # "Id": "cd611b83a0f267a1000603db52aa2d21247a32cc195c9c2b8ebcade5d35cfe1a",
  # "State": {
  #   "Status": "running",
  #   "Running": true,
  #   "Paused": false,
  #   "Restarting": false,
  #   "OOMKilled": false,
  #   "Dead": false,
  #   "Pid": 4159823,
  #   "ExitCode": 0,
  #   "Error": "",
  #   "StartedAt": "2021-05-18T22:11:49.50436001Z",
  #   "FinishedAt": "0001-01-01T00:00:00Z"

  now = datetime.datetime.now(datetime.timezone.utc)
  if attrs:
    if attrs.get("Created"):
      create_time = attrs.get("Created")
      create_dt = dateutil.parser.parse(create_time)
      create_delta = (now-create_dt).total_seconds()
      UPTIME.labels('create', miner_name).set(create_delta)
    if attrs.get("State") and attrs["State"].get("StartedAt"):
      start_time = attrs["State"]["StartedAt"]
      start_dt = dateutil.parser.parse(start_time)
      start_delta = (now-start_dt).total_seconds()
      UPTIME.labels('start', miner_name).set(start_delta)

def collect_chain_stats():
  api = safe_get_json(f'{API_BASE_URL}/blocks/height')
  if not api:
    log.error("chain height fetch returned empty JSON")
    return
  height_val = api['data']['height']
  CHAIN_STATS.labels('height').set(height_val)

  api = None
  api = safe_get_json(f'{API_BASE_URL}/validators/stats')
  if not api:
    log.error("val stats stats fetch returned empty JSON")
    return
  count_val = api['data']['staked']['count']
  CHAIN_STATS.labels('staked_validators').set(count_val)
# persist these between calls

hval = {}
def collect_hbbft_performance(docker_container, miner_name):  
  # parse the hbbft performance table for the penalty field
  out = docker_container.exec_run('miner hbbft perf --format csv')
  #print(out.output)

  for line in out.output.decode('utf-8').split("\n"):
    c = [x.strip() for x in line.split(',')]
    # samples:

    have_data = False

    if len(c) == 7 and miner_name == c[0]:
      # name,bba_completions,seen_votes,last_bba,last_seen,tenure,penalty
      # great-clear-chinchilla,5/5,237/237,0,0,2.91,2.91
      log.debug(f"resl7: {c}; {miner_name}/{c[0]}")

      (hval['bba_votes'],hval['bba_tot'])=c[1].split("/")
      (hval['seen_votes'],hval['seen_tot'])=c[2].split("/")
      hval['bba_last_val']=try_float(c[3])
      hval['seen_last_val']=try_float(c[4])
      hval['tenure'] = try_float(c[5])
      hval['pen_val'] = try_float(c[6])
    elif len(c) == 6 and miner_name == c[0]:
      # name,bba_completions,seen_votes,last_bba,last_seen,penalty
      # curly-peach-owl,11/11,368/368,0,0,1.86
      log.debug(f"resl6: {c}; {miner_name}/{c[0]}")

      (hval['bba_votes'],hval['bba_tot'])=c[1].split("/")
      (hval['seen_votes'],hval['seen_tot'])=c[2].split("/")
      hval['bba_last_val']=try_float(c[3])
      hval['seen_last_val']=try_float(c[4])
      hval['pen_val'] = try_float(c[5])
      
    elif len(c) == 6:
      # not our line
      pass
    elif len(line) == 0:
      # empty line
      pass
    else:
      log.debug(f"wrong len ({len(c)}) for hbbft: {c}")

    # always set these, that way they get reset when out of CG
    HBBFT_PERF.labels('hbbft_perf','Penalty', miner_name).set(hval.get('pen_val', 0))
    HBBFT_PERF.labels('hbbft_perf','BBA_Total', miner_name).set(hval.get('bba_tot', 0))
    HBBFT_PERF.labels('hbbft_perf','BBA_Votes', miner_name).set(hval.get('bba_votes', 0))
    HBBFT_PERF.labels('hbbft_perf','Seen_Total', miner_name).set(hval.get('seen_tot', 0))
    HBBFT_PERF.labels('hbbft_perf','Seen_Votes', miner_name).set(hval.get('seen_votes', 0))
    HBBFT_PERF.labels('hbbft_perf','BBA_Last', miner_name).set(hval.get('bba_last_val', 0))
    HBBFT_PERF.labels('hbbft_perf','Seen_Last', miner_name).set(hval.get('seen_last_val', 0))
    HBBFT_PERF.labels('hbbft_perf','Tenure', miner_name).set(hval.get('tenure', 0))


def collect_balance(miner_name):
  validator = get_validator_ledger(miner_name)
  
  if validator is None:
      log.warning(f"failed to find validator {miner_name}")
      return
  
  owner_address = validator['owner_address']
  bones = jsonRpcClient.ledger_balance(owner_address)["balance"]
  balance = float(bones)/1E8
  BALANCE.labels(miner_name).set(balance)

def collect_miner_height(miner_name):
  # grab the local blockchain height
  height = jsonRpcClient.info_height()["height"]
  VAL.labels('Height', miner_name).set(height)

def collect_in_consensus(miner_name):
  # check if currently in consensus group
  in_consensus = (1,0)[jsonRpcClient.info_in_consensus()]
  INCON.labels(miner_name).set(in_consensus)

def collect_block_age(miner_name):
  block_age = jsonRpcClient.info_block_age()
  BLOCKAGE.labels('BlockAge', miner_name).set(block_age)
  log.debug(f"block age: {block_age}")

def collect_peer_book(miner_name):
  book = jsonRpcClient.peer_book("self")[0]  
  connections = book["connection_count"]
  CONNECTIONS.labels('connections', miner_name).set(connections)

  sessions = len(book["sessions"])
  SESSIONS.labels('sessions', miner_name).set(sessions)

def collect_ledger_validators(miner_name):
  validator = get_validator_ledger(miner_name)
  
  if validator is None:
      log.warning(f"failed to find validator {miner_name}")
      return
  
  tenure_penalty = float(validator['tenure_penalty'])
  dkg_penalty = float(validator['dkg_penalty'])
  performance_penalty = float(validator['performance_penalty'])
  total_penalty = float(validator['total_penalty'])
  
  log.info(f"L penalty: {total_penalty}")
  LEDGER_PENALTY.labels('ledger_penalties', 'tenure', miner_name).set(tenure_penalty)
  LEDGER_PENALTY.labels('ledger_penalties', 'dkg', miner_name).set(dkg_penalty)
  LEDGER_PENALTY.labels('ledger_penalties', 'performance', miner_name).set(performance_penalty)
  LEDGER_PENALTY.labels('ledger_penalties', 'total', miner_name).set(total_penalty)
  
  last_heartbeat = validator['last_heartbeat']
  BLOCKAGE.labels('last_heartbeat', miner_name).set(last_heartbeat)
  
  miner_version = validator["version"]
  VALIDATOR_VERSION.labels(miner_name).info({'version': miner_version})

def get_validator_ledger(miner_name):
  validators = jsonRpcClient.ledger_validators()
  validator = next((v for v in validators if v["name"] == miner_name), None)
  return validator

if __name__ == '__main__':
  print(f"collecting metrics for: {jsonRpcClient.info_name()}")

  prometheus_client.start_http_server(9825) # 9-VAL on your phone
  while True:
    #log.warning("starting loop.")
    try:
      stats()
    except ValueError as ex:
      log.error(f"stats loop failed.", exc_info=ex)
    except docker.errors.APIError as ex:
      log.error(f"stats loop failed with a docker error.", exc_info=ex)


    # sleep 30 seconds
    time.sleep(UPDATE_PERIOD)
