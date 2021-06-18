#!/usr/bin/env python3

# external packages
import prometheus_client
import psutil
import docker
import requests
import dateutil.parser

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
log.setLevel(logging.DEBUG)

# time to sleep between scrapes
UPDATE_PERIOD = int(os.environ.get('UPDATE_PERIOD', 30))
VALIDATOR_CONTAINER_NAME = os.environ.get('VALIDATOR_CONTAINER_NAME', 'validator')

# prometheus exporter types Gauge,Counter,Summary,Histogram,Info and Enum
SCRAPE_TIME = prometheus_client.Summary('validator_scrape_time', 'Time spent collecting miner data')
SYSTEM_USAGE = prometheus_client.Gauge('system_usage',
                                       'Hold current system resource usage',
                                       ['resource_type','validator_name'])
HEIGHT = prometheus_client.Gauge('validator_height',
                              'Height of the blockchain',
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

class validator:
    def __init__(self,host,port):
        self.session = requests.Session()
        self.host = 'http://'+host+':'+str(port)
        self.header = {'Content-type': 'application/json'}
        self.payload = {"jsonrpc":"2.0",
                        "id":1,
                        "method":""}
        # bug in miner that returns name as bytes. the join can eventually be removed
        self.name = ''.join(map(chr,self.get('info_name')['name']))
        log.info(f"Name {self.name}")

    def get(self,cmd):
        self.payload["method"]=cmd
        try:
            response=self.session.post(self.host, json=self.payload, headers=self.header).json()['result']
        except KeyError:
            response=self.session.post(self.host, json=self.payload, headers=self.header).json()
        log.debug(f"response {response}")
        return(response) 


miner_facts = {}

def try_int(v):
  if re.match(r"^\-?\d+$", v):
    return int(v)
  return v

def try_float(v):
  if re.match(r"^\-?[\d\.]+$", v):
    return float(v)
  return v

def get_facts(docker_container_obj):
  if miner_facts:
    return miner_facts
  #miner_facts = {
  #  'name': None,
  #  'address': None
  #}
  out = docker_container_obj.exec_run('miner print_keys')
  # sample output:
  # {pubkey,"1YBkf..."}.
  # {onboarding_key,"1YBkf..."}.
  # {animal_name,"one-two-three"}.

  log.debug(out.output)
  printkeys = {}
  for line in out.output.split(b"\n"):
    strline = line.decode('utf-8')

    # := requires py3.8
    if m := re.match(r'{([^,]+),"([^"]+)"}.', strline):
      log.debug(m)
      k = m.group(1)
      v = m.group(2)
      log.debug(k,v)
      printkeys[k] = v

  if v := printkeys.get('pubkey'):
    miner_facts['address'] = v
  if printkeys.get('animal_name'):
    miner_facts['name'] = v
  #$ docker exec validator miner print_keys
  return miner_facts


# Decorate function with metric.
@SCRAPE_TIME.time()
def stats(validator):
  try:
    dc = docker.DockerClient()
    docker_container = dc.containers.get(VALIDATOR_CONTAINER_NAME)
    miner_facts = get_facts(docker_container)
    hotspot_name_str = validator.name
  except docker.errors.NotFound as ex:
    log.error(f"docker failed while bootstrapping. Not exporting anything. Error: {ex}")
    return

  # collect total cpu and memory usage. Might want to consider just the docker
  # container with something like cadvisor instead
  SYSTEM_USAGE.labels('CPU', hotspot_name_str).set(psutil.cpu_percent())
  SYSTEM_USAGE.labels('Memory', hotspot_name_str).set(psutil.virtual_memory()[2])

  collect_container_run_time(docker_container, hotspot_name_str)
  collect_miner_version(docker_container, hotspot_name_str)
  collect_block_age(docker_container, hotspot_name_str)
  collect_miner_height(validator)
  collect_in_consensus(validator)
  collect_ledger_validators(docker_container, hotspot_name_str)
  collect_peer_book(docker_container, hotspot_name_str)
  collect_hbbft_performance(docker_container, hotspot_name_str)
  collect_balance(docker_container,miner_facts['address'],hotspot_name_str)

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

def collect_balance(docker_container, addr, miner_name):
  # should move pubkey to getfacts and then pass it in here
  #out = docker_container.exec_run('miner print_keys')
  #for line in out.output.decode('utf-8').split("\n"):
  #  if 'pubkey' in line:
  #    addr=line[9:60]
  api_validators = safe_get_json(f'https://testnet-api.helium.wtf/v1/validators/{addr}')
  if not api_validators:
    log.error("validator fetch returned empty JSON")
    return
  elif not api_validators.get('data') or not api_validators['data'].get('owner'):
    log.error("could not find validator data owner in json")
    return
  owner = api_validators['data']['owner']

  api_accounts = safe_get_json(f'https://testnet-api.helium.wtf/v1/accounts/{owner}')
  if not api_accounts:
    return
  if not api_accounts.get('data') or not api_accounts['data'].get('balance'):
    return
  balance = float(api_accounts['data']['balance'])/1E8
  #print(api_accounts)
  #print('balance',balance)
  BALANCE.labels(miner_name).set(balance)


def collect_miner_height(validator):
  # grab the local blockchain height
  #out = docker_container.exec_run('miner info height')
  out = validator.get('info_height')
  
  log.info(f"Epoch {out['epoch']}")
  log.info(f"Height {out['height']}")
  
  HEIGHT.labels('Height', validator.name).set(out['height'])
  HEIGHT.labels('Epoch', validator.name).set(out['epoch'])


def collect_in_consensus(validator):
  # check if currently in consensus group
  out = validator.get('info_in_consensus')

  incon_txt = out['in_consensus']
  incon = 0
  if incon_txt == 'true':
    incon = 1
  log.info(f"in consensus? {incon} / {incon_txt}")
  INCON.labels(validator.name).set(incon)

def collect_block_age(docker_container, miner_name):
  # collect current block age
  out = docker_container.exec_run('miner info block_age')
  ## transform into a number
  age_val = try_int(out.output.decode('utf-8').rstrip("\n"))

  BLOCKAGE.labels('BlockAge', miner_name).set(age_val)
  log.debug(f"age: {age_val}")

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

def collect_peer_book(docker_container, miner_name):
  # peer book -s output
  out = docker_container.exec_run('miner peer book -s --format csv')
  # parse the peer book output

  # samples
  # address,name,listen_addrs,connections,nat,last_updated
  # /p2p/1YBkfTYH8iCvchuTevbCAbdni54geDjH95yopRRznZtAur3iPrM,bright-fuchsia-sidewinder,1,6,none,203.072s
  # listen_addrs (prioritized)
  # /ip4/174.140.164.130/tcp/2154
  # local,remote,p2p,name
  # /ip4/192.168.0.4/tcp/2154,/ip4/72.224.176.69/tcp/2154,/p2p/1YU2cE9FNrwkTr8RjSBT7KLvxwPF9i6mAx8GoaHB9G3tou37jCM,clever-sepia-bull

  sessions = 0
  for line in out.output.decode('utf-8').split("\r\n"):
    c = line.split(',')
    if len(c) == 6:
      log.debug(f"peerbook entry6: {c}")
      (address,peer_name,listen_add,connections,nat,last_update) = c
      conns_num = try_int(connections)

      if miner_name == peer_name and isinstance(conns_num, int):
        CONNECTIONS.labels('connections', miner_name).set(conns_num)

    elif len(c) == 4:
      # local,remote,p2p,name
      log.debug(f"peerbook entry4: {c}")
      if c[0] != 'local':
        sessions += 1
    elif len(c) == 1:
      log.debug(f"peerbook entry1: {c}")
      # listen_addrs
      pass
    else:
      log.warning(f"could not understand peer book line: {c}")

  log.debug(f"sess: {sessions}")
  SESSIONS.labels('sessions', miner_name).set(sessions)

def collect_ledger_validators(docker_container, miner_name):
  # ledger validators output
  out = docker_container.exec_run('miner ledger validators --format csv')
  results = out.output.decode('utf-8').split("\n")
  # parse the ledger validators output
  for line in [x.rstrip("\r\n") for x in results]:
    c = line.split(',')
    #print(f"{len(c)} {c}")
    if len(c) == 10:
      if c[0] == 'name' and c[1] == 'owner_address':
        # header line
        continue

      (val_name,address,last_heartbeat,stake,status,version,tenure_penalty,dkg_penalty,performance_penalty,total_penalty) = c
      if miner_name == val_name:
        log.debug(f"have pen line: {c}")
        tenure_penalty_val = try_float(tenure_penalty)
        dkg_penalty_val = try_float(dkg_penalty)
        performance_penalty_val = try_float(performance_penalty)
        total_penalty_val = try_float(total_penalty)
        least_heartbeat=try_float(last_heartbeat)

        log.info(f"L penalty: {total_penalty_val}")
        LEDGER_PENALTY.labels('ledger_penalties', 'tenure', miner_name).set(tenure_penalty_val)
        LEDGER_PENALTY.labels('ledger_penalties', 'dkg', miner_name).set(dkg_penalty_val)
        LEDGER_PENALTY.labels('ledger_penalties', 'performance', miner_name).set(performance_penalty_val)
        LEDGER_PENALTY.labels('ledger_penalties', 'total', miner_name).set(total_penalty_val)
        BLOCKAGE.labels('last_heartbeat', miner_name).set(last_heartbeat)

    elif len(line) == 0:
      # empty lines are fine
      pass
    else:
      log.warning(f"failed to grok line: {c}; section count: {len(c)}")


def collect_miner_version(docker_container, miner_name):
  out = docker_container.exec_run('miner versions')
  results = out.output.decode('utf-8').split("\n")
  # sample output
  # $ docker exec validator miner versions
  # Installed versions:
  # * 0.1.48	permanent
  for line in results:
    if m := re.match('^\*\s+([\d\.]+)(.*)', line):
      miner_version = m.group(1)
      log.info(f"found miner version: {miner_version}")
      VALIDATOR_VERSION.labels(miner_name).info({'version': miner_version})


if __name__ == '__main__':
  prometheus_client.start_http_server(9825) # 9-VAL on your phone
  v=validator('localhost','4467')
  while True:
    #log.warning("starting loop.")
    try:
      stats(v)
    except ValueError as ex:
      log.error(f"stats loop failed.", exc_info=ex)
    except docker.errors.APIError as ex:
      log.error(f"stats loop failed with a docker error.", exc_info=ex)


    # sleep 30 seconds
    time.sleep(UPDATE_PERIOD)

