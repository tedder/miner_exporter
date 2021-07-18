#!/usr/bin/env python3

# external packages
import prometheus_client
import requests

# internal packages
import datetime
import time
import os
import logging
import typing
from miner_jsonrpc import MinerJSONRPC

# remember, levels: debug, info, warning, error, critical. there is no trace.
logging.basicConfig(format="%(filename)s:%(funcName)s:%(lineno)d:%(levelname)s\t%(message)s", level=logging.WARNING)
log = logging.getLogger(__name__)
log.setLevel(logging.INFO)

# time to sleep between scrapes
UPDATE_PERIOD = int(os.environ.get('UPDATE_PERIOD', 30))
# for testnet, https://testnet-api.helium.wtf/v1
API_BASE_URL = os.environ.get('API_BASE_URL', 'https://api.helium.io/v1')

# prometheus exporter types Gauge,Counter,Summary,Histogram,Info and Enum
SCRAPE_TIME = prometheus_client.Summary('validator_scrape_time', 'Time spent collecting miner data')
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

# Last known HBBFT performance stats for this validator.
hval = {}

# Decorate function with metric.
@SCRAPE_TIME.time()
def stats(miner: MinerJSONRPC):
    try:
        addr = miner.addr()
    except:
        # This is a non-recoverable error, so many things
        # depend on knowing the address that it's silly
        # to attempt to proceed without it.
        log.error("can't get validator's address")
        return

    try:
        name = miner.name()
    except:
        # This is a non-recoverable error, so many things
        # depend on knowing the address that it's silly
        # to attempt to proceed without it.
        log.error("can't get validator's name")
        return

    #
    # Safely try to obtain as many items as possible.
    #
    height_info = None
    try:
        height_info = miner.info_height()
    except:
        log.error("chain height fetch failure")

    in_consensus = None
    try:
        in_consensus = miner.in_consensus()
    except:
        log.error("in consensus fetch failure")

    validators = None
    try:
        validators = miner.ledger_validators()
    except:
        log.error("validator fetch failure")

    this_validator = None
    if validators is not None:
        for validator in validators:
            if validator['address'] == addr:
                this_validator = validator
                break

    owner = None
    if this_validator is not None:
        owner = this_validator['owner_address']

    balance = None
    if owner is not None:
        try:
            balance_result = miner.ledger_balance({ "address" : owner })
            balance = balance_result['balance'] / 1.0e8
        except:
            log.error("owner balance fetch failure")

    block_age = None
    try:
        block_age = miner.block_age()
    except:
        log.error("block age fetch failure")

    hbbft_perf = None
    try:
        hbbft_perf = miner.hbbft_perf()
    except:
        log.error("hbbft perf fetch failure")

    peer_book_info = None
    try:
        peer_book_info = miner.peer_book_self()
    except:
        log.error("peer book self fetch failure")

    #
    # Parse results, update gauges.
    #

    # Use the validator name as the label for all validator-
    # related metrics
    my_label = name

    if height_info is not None:
        # If `sync_height` is present then the validator is
        # syncing and behind, otherwise it is in sync.
        chain_height = height_info['height']
        val_height = height_info.get('sync_height', chain_height)

        VAL.labels('Height', my_label).set(val_height)
        # TODO, consider getting this from the API
        CHAIN_STATS.labels('Height').set(chain_height)

    if in_consensus is not None:
        INCON.labels(my_label).set(in_consensus)

    if validators is not None:
        staked_validators = [ v for v in validators if v['status'] == 'staked' ]
        CHAIN_STATS.labels('staked_validators').set(len(staked_validators))

    if balance is not None:
        BALANCE.labels(my_label).set(balance)

    if block_age is not None:
        BLOCKAGE.labels('BlockAge', my_label).set(block_age)

    if this_validator is not None:
        LEDGER_PENALTY.labels('ledger_penalties', 'tenure', my_label).set(this_validator['tenure_penalty'])
        LEDGER_PENALTY.labels('ledger_penalties', 'dkg', my_label).set(this_validator['dkg_penalty'])
        LEDGER_PENALTY.labels('ledger_penalties', 'performance', my_label).set(this_validator['performance_penalty'])
        LEDGER_PENALTY.labels('ledger_penalties', 'total', my_label).set(this_validator['total_penalty'])
        BLOCKAGE.labels('last_heartbeat', my_label).set(this_validator['last_heartbeat'])

    # Update HBBFT performance stats, if in CG
    this_hbbft_perf = None
    if hbbft_perf is not None:
        for member in hbbft_perf['consensus_members']:
            if member['address'] == addr:
                this_hbbft_perf = member
                break

    if this_hbbft_perf is not None:
        # Values common to all members of the CG
        hval['bba_tot'] = hbbft_perf['blocks_since_epoch']
        hval['seen_tot'] = hbbft_perf['max_seen']

        # Values for this validator
        hval['pen_val'] = this_hbbft_perf['penalty']
        hval['tenure'] = this_hbbft_perf['tenure']
        hval['seen_votes'] = this_hbbft_perf['seen_votes']
        hval['seen_last_val'] = this_hbbft_perf['last_seen']
        hval['bba_last_val'] = this_hbbft_perf['last_bba']
        hval['bba_completions'] = this_hbbft_perf['bba_completions']

    # always set these, that way they get reset when out of CG
    HBBFT_PERF.labels('hbbft_perf','Penalty', my_label).set(hval.get('pen_val', 0))
    HBBFT_PERF.labels('hbbft_perf','BBA_Total', my_label).set(hval.get('bba_tot', 0))
    HBBFT_PERF.labels('hbbft_perf','BBA_Votes', my_label).set(hval.get('bba_completions', 0))
    HBBFT_PERF.labels('hbbft_perf','Seen_Total', my_label).set(hval.get('seen_tot', 0))
    HBBFT_PERF.labels('hbbft_perf','Seen_Votes', my_label).set(hval.get('seen_votes', 0))
    HBBFT_PERF.labels('hbbft_perf','BBA_Last', my_label).set(hval.get('bba_last_val', 0))
    HBBFT_PERF.labels('hbbft_perf','Seen_Last', my_label).set(hval.get('seen_last_val', 0))
    HBBFT_PERF.labels('hbbft_perf','Tenure', my_label).set(hval.get('tenure', 0))

    if peer_book_info is not None:
        connections = peer_book_info[0]['connection_count']
        CONNECTIONS.labels('connections', my_label).set(connections)
        sessions = len(peer_book_info[0]['sessions'])
        SESSIONS.labels('sessions', my_label).set(sessions)


if __name__ == '__main__':
  prometheus_client.start_http_server(9825) # 9-VAL on your phone
  miner = MinerJSONRPC('http://localhost:4467/')
  while True:
    #log.warning("starting loop.")
    try:
      stats(miner)
    except ValueError as ex:
      log.error(f"stats loop failed.", exc_info=ex)

    # sleep 30 seconds
    time.sleep(UPDATE_PERIOD)

