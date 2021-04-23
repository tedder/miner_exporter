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
                             ['resource_type'])

def try_int(v):
  if re.match(r"^\-?\d+$", v):
    return int(v)
  return v

def try_float(v):
  if re.match(r"^\-?[\d\.]+$", v):
    return float(v)
  return v

def stats():
  dc = docker.DockerClient()
  docker_container = dc.containers.get(VALIDATOR_CONTAINER_NAME)

  # collect total cpu and memory usage. Might want to consider just the docker
  # container with something like cadvisor instead
  SYSTEM_USAGE.labels('CPU').set(psutil.cpu_percent())
  SYSTEM_USAGE.labels('Memory').set(psutil.virtual_memory()[2])

  # grab the local blockchain height
  out = docker_container.exec_run('miner info height')
  print(out.output)
  VAL.labels('Height').set(out.output.split()[1])

  # need to fix this. hotspot name really should only be queried once
  out = docker_container.exec_run('miner info name')
  print(out.output)
  hotspot_name = out.output.rstrip(b"\n")
  hotspot_name_str = hotspot_name.decode('utf-8')

  # check if currently in consensus group
  out = docker_container.exec_run('miner info in_consensus')
  print(out.output)
  incon = 0
  if out.output.rstrip(b"\n") == 'true':
    incon = 1
  print(f"in consensus? {incon}")
  INCON.labels(hotspot_name_str).set(incon)

  # collect current block age
  out = docker_container.exec_run('miner info block_age')
  ## transform into a number
  age_val = try_int(out.output.rstrip(b"\n").decode('utf-8'))

  BLOCKAGE.labels('BlockAge').set(age_val)
  print(f"age: {age_val}")

  # parse the hbbft performance table for the penalty field
  out = docker_container.exec_run('miner hbbft perf')
  print(out.output)
  results = out.output.split(b"\n")
  for line in results:
    if hotspot_name in line and len(line.split()) > 12:
      results = line.split()[12]
      PENALTY.labels('Penalty').set(results)
      print(f"pen: {results}")

  # peer book -s output
  out=docker_container.exec_run('miner peer book -s')
  results=out.output.split(b"\n")
  # parse the peer book output  
  sessions=0  
  for line in results:
    c=line.split(b'|')
    if len(c)==8:
      garbage1,address,peer_name,listen_add,connections,nat,last_update,garbage2=c
    elif len(c)==6:
      sessions=sessions+1
  conns_num = try_int(connections.strip().decode('utf-8'))
  CONNECTIONS.labels('connections').set(conns_num)
  print(f"conns: {conns_num}")
  SESSIONS.labels('sessions').set(sessions-1)
  print(f"sess: {sessions-1}")

  # ledger validators output
  out=docker_container.exec_run('miner ledger validators')
  results=out.output.split(b"\n")
  # parse the ledger validators output  
  validators={}
  for line in results:
    c=line.split(b'|')
    if len(c) == 9:
      (_,val_name,address,last_heard,stake,status,version,penalty,_) = c
      val_name_str=val_name.strip().decode('utf-8')
      if val_name_str in hotspot_name_str:
        penalty_val = try_float(penalty.strip().decode('utf-8'))
        validators[hotspot_name_str] = penalty_val
    else:
      print(f"failed to grok line: {c}")

  LEDGER_PENALTY.labels('ledger_penalty').set(validators[hotspot_name_str])
  print(f"vals: {validators[hotspot_name_str]}")


if __name__ == '__main__':
  prometheus_client.start_http_server(8000)
  while True:
    stats()

    # sleep 30 seconds
    time.sleep(UPDATE_PERIOD)

