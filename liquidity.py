from uniswapv2 import UniswapV2
from utils import  decimal_round, is_percent_down, is_percent_up, pancakeswap_api_get_price
from decimal import Decimal
import logging
import traceback
import sys
import os
import time
from settings import *

VERSION = "1.0"

"""

 Liquidity watcher for all UniswapV2 smart contracts running on RPC/metmask bound chains.
 
 Will remove all liquidity from a pool that is down X% from when you started the bot.

"""


def main():
    os.system("clear")
    
    # Setup logger.
    log_format = '%(asctime)s: %(message)s'
    logging.basicConfig(level=logging.INFO, format=log_format, stream=sys.stdout)
    logging.info('Uniswap Liquidity Watcher v%s Started!' % VERSION)
    
    # token address to use when determining total value of pool
    # currently this is set to jewel.
    value_token = VALUE_TOKEN
    
    # how much percent to be down before pulling all liquidity
    percent_down_remove_liquidity = PERCENT_DOWN_REMOVE_LIQUIDITY
    
    percent_up_remove_liquidity = PERCENT_UP_REMOVE_LIQUIDITY
    
    # how much percent to be down before reporting in the log.
    percent_report_change = PERCENT_REPORT_CHANGE

    # loads pools from a csv file, so we dont have to search all liquidity pools
    # every start.
    pools_dict = load_pools_file("pools.csv")
    
    # create my spiffy new uniswap class. works for all networks and forks.
    # Added uniswap object initialization every loop incase connection is lost or something.
    uniswap = UniswapV2(
        PRIVATE_KEY, 
        txn_timeout=TXN_TIMEOUT, 
        gas_price_gwei=GAS_PRICE_IN_WEI, 
        rpc_host=RPC_HOST, 
        router_address=ROUTER_ADDRESS,
        factory_address=FACTORY_ADDRESS,
        block_explorer_prefix=BLOCK_EXPLORER_PREFIX
    )
            
    previous_worth_dict = {}
    percent_changed_dict = {}
    percent_remove_dict = {}
    initial_report_dict = {}
    previous_total_value = None
    value_token_name = None
    start_time = time.time()
    initial_report_time = time.time()
    percent_remove_time = time.time()
    while True:
        
        # Do not reset the timer until the end of the loop.
        if time.time() - initial_report_time > (REPORT_ALL_POOLS_EVERY_MINS * 60):
            initial_report_dict = {}
        
        # Force the percent remove dict to reset so that updated values are used when comparing percent up/down
        # So that it doesnt have the same starting values for all its run length time.
        # Resets this dict every 5 hours.
        if time.time() - percent_remove_time > (60 * 60 * 5):
            logging.debug('Cleared percent_remove_dict.')
            percent_remove_dict = {}
            percent_remove_time = time.time()
        
        if not value_token_name:
            value_token_name = uniswap._get_symbol(value_token)
            logging.info("Interval: %s. Currency: %s." % (CHECK_MINUTE_DELAY, value_token_name))
            
        if len(pools_dict) == 0:
            # Get all LP pairs that account is providing liquidity on.
            logging.info('No pools found. Searching for liquidity pools...')
            liquidity_pools = uniswap._get_deposited_pairs()
            for address in liquidity_pools:
                pools_dict[address] = 0.0
            logging.info('Found %s pools!' % len(pools_dict))
        
        save_pools_file(pools_dict, "pools.csv")
        current_pool_value = Decimal(0.0)
        remove_pools = []
        # Get all pool info
        for pair_address in pools_dict:
            # Get the pool info form pair address.
            pool_info = get_pair_info(uniswap, pair_address, value_token)
            if not pool_info:
                time.sleep(30)
                continue
            # Tracking dicts for watching percent change.
            pools_dict[pair_address] = pool_info["total_value"]
            if pair_address not in initial_report_dict:
                initial_report_dict[pair_address] = pool_info["total_value"]
                logging.info('symbol: %s. %s: %s. %s: %s. value: %s.' % (
                    pool_info["symbol"], pool_info["token0_name"], decimal_round(pool_info["token0_amount"], 5),
                    pool_info["token1_name"], decimal_round(pool_info["token1_amount"], 5), decimal_round(pool_info["total_value"], 5)))
            if pair_address not in percent_changed_dict:
                percent_changed_dict[pair_address] = pool_info["total_value"]
            if pair_address not in percent_remove_dict:
                percent_remove_dict[pair_address] = pool_info["total_value"]
            
            # Check the percent change of the total value of pool using the tracking dicts above.
            # on X% down this will remove all liquidity from target pair. (see options)
            if pair_address in previous_worth_dict:
                if pool_info["total_value"] > percent_changed_dict[pair_address]:
                    if is_percent_up(percent_changed_dict[pair_address], pool_info["total_value"], percent_report_change) is True:
                        logging.info('%s is ⬆ to %s from %s!' % (
                            pool_info["symbol"], round(pool_info["total_value"], 7), round(previous_worth_dict[pair_address], 7)))
                        percent_changed_dict[pair_address] = pool_info["total_value"]
                    if is_percent_up(percent_remove_dict[pair_address], pool_info["total_value"], percent_up_remove_liquidity) is True:
                        logging.info('ATTENTION: %s is UP UP UP %s percent since bot started.' % (
                            pool_info["symbol"], percent_down_remove_liquidity))
                        # set the start dicts total value, so it doesnt report on loop
                        percent_remove_dict[pair_address] = pool_info["total_value"]
                        # remove all liquidity from pair address.
                        remove_result = uniswap.remove_liquidity_from_pair(pair_address, max_tries=RPC_ATTEMPTS)
                        logging.info('remove result: %s.' % remove_result)
                        # add to remove list, so that pair is removed from processing.
                        remove_pools.append(pair_address)
                elif pool_info["total_value"] < previous_worth_dict[pair_address]:
                    if is_percent_down(percent_changed_dict[pair_address], pool_info["total_value"], percent_report_change) is True:
                        logging.info('%s is ⬇ to %s from %s!' % (
                            pool_info["symbol"], round(pool_info["total_value"], 7), round(previous_worth_dict[pair_address], 7)))
                        percent_changed_dict[pair_address] = pool_info["total_value"]
                    if is_percent_down(percent_remove_dict[pair_address], pool_info["total_value"], percent_down_remove_liquidity) is True:
                        logging.info('WARNING: %s is down %s percent since bot started.' % (
                            pool_info["symbol"], percent_down_remove_liquidity))
                        # set the start dicts total value, so it doesnt report on loop
                        percent_remove_dict[pair_address] = pool_info["total_value"]
                        # remove all liquidity from pair address.
                        remove_result = uniswap.remove_liquidity_from_pair(pair_address, max_tries=RPC_ATTEMPTS)
                        logging.info('remove result: %s.' % remove_result)
                        # add to remove list, so that pair is removed from processing.
                        remove_pools.append(pair_address)
                        
            previous_worth_dict[pair_address] = pool_info["total_value"]
            current_pool_value += Decimal(pool_info["total_value"])
            
        if previous_total_value and (is_percent_down(previous_total_value, current_pool_value, percent_report_change) is True or \
            is_percent_up(previous_total_value, current_pool_value, percent_report_change)) is True:
            report_total = True
        elif previous_total_value is None:
            report_total = True
        else:
            report_total = False
        
        # Reset counter for reporting the pool total values.
        if time.time() - initial_report_time > (REPORT_ALL_POOLS_EVERY_MINS * 60):
            initial_report_dict = time.time()
            report_total = True
        
        if report_total is True:
            previous_total_value = current_pool_value
            logging.info("Total (in %s): %s" % (value_token_name, str(decimal_round(current_pool_value, 8))))
            
        for remove in remove_pools:
            try:
                del pools_dict[remove]
            except:
                logging.debug(traceback.format_exc())
        
        time.sleep(CHECK_MINUTE_DELAY * 60)
    
def get_pair_info(client, pair_address, value_token):
    pool_info = None
    for _ in range(RPC_ATTEMPTS):
        pool_info = client._get_pool_info(
            pair_address,  # The liquidity pair contract address.
            value_token=value_token  # Value token is jewel.
        )
        if pool_info:
            break
    return pool_info
        
def load_pools_file(filename):
    pools_dict = {}
    if os.path.exists(filename) is True:
        try:
            with open(filename, 'r') as fp:
                temp_lines = fp.readlines()
            for t_line in temp_lines:
                if ',' in t_line:
                    address, value = t_line.split(',')
                    pools_dict[address] = value
        except:
            logging.debug(traceback.format_exc())
    return pools_dict
        
def save_pools_file(pool_dict, filename):
    try:
        with open(filename, "w") as fp:
            for address in pool_dict:
                fp.write("%s,%s\n" % (address, pool_dict[address]))
    except:
        logging.debug(traceback.format_exc())

def get_token_price(token):
    price_dict = pancakeswap_api_get_price(token)
    token_price = price_dict["data"]["price"]
    return token_price

if __name__ == "__main__":
    main()