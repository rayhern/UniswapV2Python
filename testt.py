from uniswapv2 import UniswapV2
from utils import *
from decimal import Decimal
import logging
import traceback
import sys
import os
import time
from settings import *

def main():

    # Setup logger.
    log_format = '%(asctime)s: %(message)s'
    logging.basicConfig(level=logging.INFO, format=log_format, stream=sys.stdout)
    
    uniswap = UniswapV2(
        PRIVATE_KEY, 
        txn_timeout=TXN_TIMEOUT, 
        gas_price_gwei=GAS_PRICE_IN_WEI, 
        rpc_host=RPC_HOST, 
        router_address=ROUTER_ADDRESS,
        factory_address=FACTORY_ADDRESS,
        block_explorer_prefix=BLOCK_EXPLORER_PREFIX
    )
    
    price = uniswap.get_price_for_amount(
        eth2wei(1), 
        "0x72Cb10C6bfA5624dD07Ef608027E366bd690048F",
    )
    logging.info(price)

if __name__ == "__main__":
    main()