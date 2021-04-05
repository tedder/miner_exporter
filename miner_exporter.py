# external packages
import prometheus_client
import psutil

# internal packages
import time
import subprocess

# time to sleep between scrapes
UPDATE_PERIOD = 30

# miner commands
cmd_height = 'docker exec validator miner info height'.split()
cmd_name = 'docker exec validator miner info name'.split()
cmd_incon = 'docker exec validator miner info in_consensus'.split()
cmd_blockage = 'docker exec validator miner info block_age'.split()
cmd_hbbft_perf = 'docker exec validator miner hbbft perf'.split()

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

if __name__ == '__main__':
  prometheus_client.start_http_server(8000)
  
while True:
  # collect total cpu and memory usage. Might want to consider just the docker
  # container with something like cadvisor instead
  SYSTEM_USAGE.labels('CPU').set(psutil.cpu_percent())
  SYSTEM_USAGE.labels('Memory').set(psutil.virtual_memory()[2])

  # grab the local blockchain height
  out=subprocess.run(cmd_height,
                   #stdout=subprocess.DEVNULL,
                   #stderr=subprocess.DEVNULL
                   capture_output=True,
                   universal_newlines=True,
                   text=True) 
  VAL.labels('Height').set(out.stdout.split()[1])

  # need to fix this. hotspot name really should only be queried once
  out=subprocess.run(cmd_name,
                   capture_output=True,
                   universal_newlines=True,
                   text=True)
  name=out.stdout.rstrip('\n')

  # check if currently in consensus group
  out=subprocess.run(cmd_incon,
                   capture_output=True,
                   universal_newlines=True,
                   text=True)
  if(out.stdout.rstrip('\n')=='true'):
    incon=1
  else:
    incon=0  
  INCON.labels(name).set(incon)

  # collect current block age
  out=subprocess.run(cmd_blockage,
                   capture_output=True,
                   universal_newlines=True,
                   text=True)
  BLOCKAGE.labels('BlockAge').set(out.stdout)

  # parse the hbbft performance table for the penalty field
  out=subprocess.run(cmd_hbbft_perf,
                   capture_output=True,
                   universal_newlines=True,
                   text=True)
  results=out.stdout
  results=results.split('\n')
  try: 
    for line in results:
        if name in line:
            results=line.split()[12]
            PENALTY.labels('Penalty').set(results)     
  except:
    pass

  # sleep 30 seconds
  time.sleep(UPDATE_PERIOD)
 
