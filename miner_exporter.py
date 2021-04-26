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
                                       ['resource_type'])
VAL = prometheus_client.Gauge('validator_height',
                              'Height of the blockchain',
                              ['resource_type'])

INCON = prometheus_client.Gauge('validator_inconsensus',
                              'Is validator currently in consensus group',
                              ['resource_type'])
BLOCKAGE = prometheus_client.Gauge('validator_block_age',
                              'Age of the current block',
                             ['resource_type'])
PENALTY = prometheus_client.Gauge('validator_hbbft_penalty',
                              'HBBFT Penalty metrit from perf ',
                             ['resource_type'])
CONNECTIONS = prometheus_client.Gauge('validator_connections',
                              'Number of libp2p connections ',
                             ['resource_type'])
SESSIONS = prometheus_client.Gauge('validator_sessions',
                              'Number of libp2p sessions',
                             ['resource_type'])
LEDGER_PENALTY = prometheus_client.Gauge('validator_ledger',
                              'Validator performance metrics ',
                             ['resource_type', 'subtype'])
VALIDATOR_VERSION = prometheus_client.Info('validator_version',
                              'Version number of the miner container')

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

  # collect total cpu and memory usage. Might want to consider just the docker
  # container with something like cadvisor instead
  SYSTEM_USAGE.labels('CPU').set(psutil.cpu_percent())
  SYSTEM_USAGE.labels('Memory').set(psutil.virtual_memory()[2])

  hotspot_name_str = get_miner_name(docker_container)

  collect_miner_version(docker_container)
  collect_block_age(docker_container)
  collect_miner_height(docker_container)
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

def collect_miner_height(docker_container):
  # grab the local blockchain height
  out = docker_container.exec_run('miner info height')
  print(out.output)
  txt = out.output.decode('utf-8').rstrip("\n")
  VAL.labels('Height').set(out.output.split()[1])

def collect_in_consensus(docker_container, hotspot_name_str):
  # check if currently in consensus group
  out = docker_container.exec_run('miner info in_consensus')
  incon_txt = out.output.decode('utf-8').rstrip("\n")
  incon = 0
  if incon_txt == 'true':
    incon = 1
  print(f"in consensus? {incon} / {incon_txt}")
  INCON.labels(hotspot_name_str).set(incon)

def collect_block_age(docker_container):
  # collect current block age
  out = docker_container.exec_run('miner info block_age')
  ## transform into a number
  age_val = try_int(out.output.decode('utf-8').rstrip("\n"))

  BLOCKAGE.labels('BlockAge').set(age_val)
  print(f"age: {age_val}")

def collect_hbbft_performance(docker_container, hotspot_name_str):
  # parse the hbbft performance table for the penalty field
  out = docker_container.exec_run('miner hbbft perf')
  print(out.output)
  for line in out.output.decode('utf-8').split("\n"):
    c = [x.strip() for x in line.split('|')]
    if len(c) == 8 and hotspot_name_str.startswith(c[1]):
      print(f"resl: {c}; {hotspot_name_str}/{c[1]}")
      pen_val = try_float(c[6])
      print(f"pen: {pen_val}")
      PENALTY.labels('Penalty').set(pen_val)
    elif len(c) == 8:
      # not our line
      pass
    elif len(line) == 0:
      # empty line
      pass
    elif re.match('^[\+\-]+$', line):
      # e.g., "+--------------+-------------"
      # table formatting lines are fine
      pass
    else:
      print(f"wrong len for hbbft: {c}")

def collect_peer_book(docker_container, hotspot_name_str):
  # peer book -s output
  out = docker_container.exec_run('miner peer book -s')
  # parse the peer book output
  sessions = 0
  for line in out.output.decode('utf-8').split("\n"):
    c = line.split('|')
    if len(c) == 8:
      print(f"peerbook entry8: {c}")
      (_,address,peer_name,listen_add,connections,nat,last_update,_) = c
      conns_num = try_int(connections.strip())

      if hotspot_name_str.startswith(peer_name) and isinstance(conns_num, int):
        print(f"conns: {conns_num}")
        CONNECTIONS.labels('connections').set(conns_num)

    elif len(c) == 6:
      print(f"peerbook entry6: {c}")
      sessions += 1

  print(f"sess: {sessions-1}")
  SESSIONS.labels('sessions').set(sessions-1)

def collect_ledger_validators(docker_container, hotspot_name_str):
  # ledger validators output
  out = docker_container.exec_run('miner ledger validators')
  results = out.output.split(b"\n")
  # parse the ledger validators output
  for line in results:
    line = line.decode('utf-8')
    c = line.split('|')
    print(f"{len(c)} {c}")
    if len(c) == 12:
      (_,val_name,address,last_heard,stake,status,version,tenure_penalty,dkg_penalty,performance_penalty,total_penalty,_) = c
      val_name_str = val_name.strip()
      if hotspot_name_str.startswith(val_name_str):
        tenure_penalty_val = try_float(tenure_penalty.strip())
        dkg_penalty_val = try_float(dkg_penalty.strip())
        performance_penalty_val = try_float(performance_penalty.strip())
        total_penalty_val = try_float(total_penalty.strip())

        LEDGER_PENALTY.labels('ledger_penalties', 'tenure').set(tenure_penalty_val)
        LEDGER_PENALTY.labels('ledger_penalties', 'dkg').set(dkg_penalty_val)
        LEDGER_PENALTY.labels('ledger_penalties', 'performance').set(performance_penalty_val)
        LEDGER_PENALTY.labels('ledger_penalties', 'total').set(total_penalty_val)

    elif len(line) == 0:
      # empty lines are fine
      pass
    elif re.match('^[\+\-]+$', line):
      # e.g., "+--------------+-------------"
      # table formatting lines are fine
      pass
    else:
      print(f"failed to grok line: {c}; section count: {len(c)}")


def collect_miner_version(docker_container):
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
      VALIDATOR_VERSION.info({'version': miner_version})


if __name__ == '__main__':
  prometheus_client.start_http_server(8000)
  while True:
    try:
      stats()
    except ValueError as ex:
      print(f"stats loop failed, {type(ex)}: {ex}")

    # sleep 30 seconds
    time.sleep(UPDATE_PERIOD)

