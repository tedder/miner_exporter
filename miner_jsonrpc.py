#!/usr/bin/env python3

# external packages
import requests

# internal packages
import logging
import typing
import functools

# remember, levels: debug, info, warning, error, critical. there is no trace.
logging.basicConfig(format="%(filename)s:%(funcName)s:%(lineno)d:%(levelname)s\t%(message)s", level=logging.WARNING)
log = logging.getLogger(__name__)
log.setLevel(logging.INFO)

class MinerJSONRPC:
    """
    JSON/RPC interface to miner data.
    """
    rpc_endpoint: str
    rpc_call_id: int
    headers: dict

    def __init__(self, endpoint: str):
        self.rpc_endpoint = endpoint
        self.rpc_call_id = 0
        self.headers = {'Content-Type': 'application/json' }

    def rpc_call(self, verb, params: dict=None) -> dict:
        data = { "jsonrpc":"2.0", "id": self.rpc_call_id, "method": verb }
        if params:
            data['params'] = params
        r = requests.post(self.rpc_endpoint, json=data)
        self.rpc_call_id += 1
        body = r.json()
        error = body.get('error')
        if error is not None:
            raise Exception('JSON/RPC error')
        return body['result']

    def addr(self) -> str:
        result = self.rpc_call('peer_addr')
        full_addr = result['peer_addr']
        return full_addr[5:]

    def name(self) -> str:
        result = self.rpc_call('info_name')
        return result['name']

    def block_age(self) -> int:
        return self.rpc_call('info_block_age')['block_age']

    def info_height(self) -> dict:
        return self.rpc_call('info_height')

    def in_consensus(self) -> bool:
        return self.rpc_call('info_in_consensus')['in_consensus']

    def peer_book_self(self) -> dict:
        return self.rpc_call('peer_book', params={ 'addr' : 'self' })

    def ledger_validators(self, **params) -> typing.List[dict]:
        return self.rpc_call('ledger_validators', params)

    def ledger_balance(self, **params) -> typing.List[dict]:
        return self.rpc_call('ledger_balance', params)

    def hbbft_perf(self) -> typing.List[dict]:
        return self.rpc_call('hbbft_perf')

def safe_get_json(url: str):
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

