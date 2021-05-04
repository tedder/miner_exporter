#!/usr/bin/env python3

# external packages
import prometheus_client
import psutil

# internal packages
import time
import subprocess
import docker
import sys
import os
import re

# time to sleep between scrapes
UPDATE_PERIOD = int(os.environ.get('UPDATE_PERIOD', 30))
VALIDATOR_CONTAINER_NAME = os.environ.get('VALIDATOR_CONTAINER_NAME', 'validator')

# prometheus exporter types Gauge,Counter,Summary,Histogram,Info and Enum
SYSTEM_USAGE = prometheus_client.Gauge('system_usage',
                                       'Hold current system resource usage',
                                       ['resource_type','validator_name'])
VAL = prometheus_client.Gauge('validator_height',
                              'Height of the blockchain',
                              ['resource_type','validator_name'])

INCON = prometheus_client.Gauge('validator_inconsensus',
                              'Is validator currently in consensus group',
                              ['validator_name'])
BLOCKAGE = prometheus_client.Gauge('validator_block_age',
                              'Age of the current block',
                             ['resource_type','validator_name'])
PENALTY = prometheus_client.Gauge('validator_hbbft_penalty',
                              'HBBFT Penalty metric from perf, only applies when in CG',
                             ['resource_type','validator_name'])
BBA_VOTES = prometheus_client.Gauge('validator_hbbft_bba_votes',
                              'HBBFT bba completions metric from perf, only applies when in CG',
                             ['resource_type','validator_name'])
BBA_TOTAL = prometheus_client.Gauge('validator_hbbft_bba_total',
                              'HBBFT bba total completions metric from perf, only applies when in CG',
                             ['resource_type','validator_name'])
SEEN_VOTES = prometheus_client.Gauge('validator_hbbft_seen_votes',
                              'HBBFT seen votes metric from perf, only applies when in CG',
                             ['resource_type','validator_name'])
SEEN_TOTAL = prometheus_client.Gauge('validator_hbbft_seen_total',
                              'HBBFT seen total metric from perf, only applies when in CG',
                             ['resource_type','validator_name'])
BBA_LAST = prometheus_client.Gauge('validator_hbbft_bba_last',
                              'HBBFT last bba from perf, only applies when in CG',
                             ['resource_type','validator_name'])
SEEN_LAST = prometheus_client.Gauge('validator_hbbft_seen_last',
                              'HBBFT last seen from perf, only applies when in CG',
                             ['resource_type','validator_name'])
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

  print(out.output)
  printkeys = {}
  for line in out.output.split(b"\n"):
    strline = line.decode('utf-8')

    # := requires py3.8
    if m := re.match(r'{([^,]+),"([^"]+)"}.', strline):
      print(m)
      k = m.group(1)
      v = m.group(2)
      print(k,v)
      printkeys[k] = v

  if v := printkeys.get('pubkey'):
    miner_facts['address'] = v
  if printkeys.get('animal_name'):
    miner_facts['name'] = v
  #$ docker exec validator miner print_keys
  return miner_facts



def stats():
  dc = docker.DockerClient()
  docker_container = dc.containers.get(VALIDATOR_CONTAINER_NAME)
  miner_facts = get_facts(docker_container)
  hotspot_name_str = get_miner_name(docker_container)

  # collect total cpu and memory usage. Might want to consider just the docker
  # container with something like cadvisor instead
  SYSTEM_USAGE.labels('CPU', hotspot_name_str).set(psutil.cpu_percent())
  SYSTEM_USAGE.labels('Memory', hotspot_name_str).set(psutil.virtual_memory()[2])


  collect_miner_version(docker_container, hotspot_name_str)
  collect_block_age(docker_container, hotspot_name_str)
  collect_miner_height(docker_container, hotspot_name_str)
  collect_in_consensus(docker_container, hotspot_name_str)
  collect_ledger_validators(docker_container, hotspot_name_str)
  collect_peer_book(docker_container, hotspot_name_str)
  collect_hbbft_performance(docker_container, hotspot_name_str)

def get_miner_name(docker_container):
  # need to fix this. hotspot name really should only be queried once
  out = docker_container.exec_run('miner info name')
  print(out.output)
  hotspot_name = out.output.decode('utf-8').rstrip("\n")
  return hotspot_name

def collect_miner_height(docker_container, miner_name):
  # grab the local blockchain height
  out = docker_container.exec_run('miner info height')
  print(out.output)
  txt = out.output.decode('utf-8').rstrip("\n")
  VAL.labels('Height', miner_name).set(out.output.split()[1])

def collect_in_consensus(docker_container, miner_name):
  # check if currently in consensus group
  out = docker_container.exec_run('miner info in_consensus')
  incon_txt = out.output.decode('utf-8').rstrip("\n")
  incon = 0
  if incon_txt == 'true':
    incon = 1
  print(f"in consensus? {incon} / {incon_txt}")
  INCON.labels(miner_name).set(incon)

def collect_block_age(docker_container, miner_name):
  # collect current block age
  out = docker_container.exec_run('miner info block_age')
  ## transform into a number
  age_val = try_int(out.output.decode('utf-8').rstrip("\n"))

  BLOCKAGE.labels('BlockAge', miner_name).set(age_val)
  print(f"age: {age_val}")

def collect_hbbft_performance(docker_container, miner_name):
  # parse the hbbft performance table for the penalty field
  out = docker_container.exec_run('miner hbbft perf --format csv')
  #print(out.output)
  for line in out.output.decode('utf-8').split("\n"):
    c = [x.strip() for x in line.split(',')]
    # samples:
    # name,bba_completions,seen_votes,last_bba,last_seen,penalty
    # curly-peach-owl,11/11,368/368,0,0,1.86

    if len(c) == 6 and miner_name == c[0]:
      print(f"resl: {c}; {miner_name}/{c[0]}")
      (bba_votes,bba_tot)=c[1].split("/")
      (seen_votes,seen_tot)=c[2].split("/")
      bba_last_val=try_float(c[3])
      seen_last_val=try_float(c[4])
      pen_val = try_float(c[5])
      PENALTY.labels('Penalty', miner_name).set(pen_val)
      BBA_TOTAL.labels('BBA_Total', miner_name).set(bba_tot)
      BBA_VOTES.labels('BBA_Votes', miner_name).set(bba_votes)
      SEEN_TOTAL.labels('Seen_Total', miner_name).set(seen_tot)
      SEEN_VOTES.labels('Seen_Votes', miner_name).set(seen_votes)
      BBA_LAST.labels('BBA_Last', miner_name).set(bba_last_val)
      SEEN_LAST.labels('Seen_Last', miner_name).set(seen_last_val)
      print(f"pen: {pen_val}")
      print(f"bba completions: {bba_votes}")
      print(f"bba total: {bba_tot}")
      print(f"bba last: {bba_last_val}")
      print(f"seen votes: {seen_votes}")
      print(f"seen total: {seen_tot}")
      print(f"seen last: {seen_last_val}")
    elif len(c) == 6:
      # not our line
      pass
    elif len(line) == 0:
      # empty line
      pass
    else:
      print(f"wrong len ({len(c)}) for hbbft: {c}")

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
      print(f"peerbook entry6: {c}")
      (address,peer_name,listen_add,connections,nat,last_update) = c
      conns_num = try_int(connections)

      if miner_name == peer_name and isinstance(conns_num, int):
        CONNECTIONS.labels('connections', miner_name).set(conns_num)

    elif len(c) == 4:
      # local,remote,p2p,name
      print(f"peerbook entry4: {c}")
      if c[0] != 'local':
        sessions += 1
    elif len(c) == 1:
      print(f"peerbook entry1: {c}")
      # listen_addrs
      pass
    else:
      print(f"could not understand peer book line: {c}")

  print(f"sess: {sessions}")
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

      (val_name,address,last_heard,stake,status,version,tenure_penalty,dkg_penalty,performance_penalty,total_penalty) = c
      if miner_name == val_name:
        print(f"have pen line: {c}")
        tenure_penalty_val = try_float(tenure_penalty)
        dkg_penalty_val = try_float(dkg_penalty)
        performance_penalty_val = try_float(performance_penalty)
        total_penalty_val = try_float(total_penalty)

        LEDGER_PENALTY.labels('ledger_penalties', 'tenure', miner_name).set(tenure_penalty_val)
        LEDGER_PENALTY.labels('ledger_penalties', 'dkg', miner_name).set(dkg_penalty_val)
        LEDGER_PENALTY.labels('ledger_penalties', 'performance', miner_name).set(performance_penalty_val)
        LEDGER_PENALTY.labels('ledger_penalties', 'total', miner_name).set(total_penalty_val)

    elif len(line) == 0:
      # empty lines are fine
      pass
    else:
      print(f"failed to grok line: {c}; section count: {len(c)}")


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
      print(f"found miner version: {miner_version}")
      VALIDATOR_VERSION.labels(miner_name).info({'version': miner_version})


if __name__ == '__main__':
  prometheus_client.start_http_server(8000)
  while True:
    try:
      stats()
    except ValueError as ex:
      print(f"stats loop failed, {type(ex)}: {ex}")

    # sleep 30 seconds
    time.sleep(UPDATE_PERIOD)

