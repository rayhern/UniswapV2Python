from web3 import Web3
from decimal import Decimal
from utils import wei2eth, eth2wei, to_checksum, read_json_file, decimal_fix_places, decimal_round
import traceback
import time
import logging
import random

ROUTER_ABI_FILE = "./abi/UniswapV2Router.json"
PAIR_ABI_FILE = "./abi/UniswapV2Pair.json"
FACTORY_ABI_FILE = "./abi/UniswapV2Factory.json"
ERC20_ABI_FILE = "./abi/ERC20.json"

class UniswapV2():
    def __init__(
        self, private_key, txn_timeout=60, gas_price_gwei=30, rpc_host="https://api.harmony.one/", slippage=10,
        router_address="0x24ad62502d1C652Cc7684081169D04896aC20f30", factory_address="0x9014B937069918bd319f80e8B3BB4A2cf6FAA5F7",
        block_explorer_prefix="https://explorer.harmony.one/tx/"):
        self.private_key = private_key
        self.txn_timeout = txn_timeout
        self.gas_price = gas_price_gwei
        self.slippage = slippage
        self.rpc_host = rpc_host
        self.router_address = router_address
        self.factory_address = factory_address
        self.block_explorer_prefix = block_explorer_prefix
        # Initialize web3, and load the smart contract objects.
        self.w3 = Web3(Web3.HTTPProvider(self.rpc_host))
        self.account = self.w3.eth.account.privateKeyToAccount(self.private_key)
        self.address = self.account.address
        self.w3.eth.default_account = self.address
        # Load uniswap router contract
        self.router_abi = read_json_file(ROUTER_ABI_FILE)
        self.router_contract = self.w3.eth.contract(
            to_checksum(self.router_address), abi=self.router_abi)
        # Load uniswap factory contract
        self.factory_abi = read_json_file(FACTORY_ABI_FILE)
        self.factory_contract = self.w3.eth.contract(
            to_checksum(self.factory_address), abi=self.factory_abi)
        # Load the pair abi file, and erc20 abi file without a contract.
        self.pair_abi = read_json_file(PAIR_ABI_FILE)
        self.erc20_abi = read_json_file(ERC20_ABI_FILE)
        self.initialized = True
        
    def get_nonce(self):
        nonce = self.w3.eth.getTransactionCount(self.address)
        return nonce
    
    def approve(self, contract_address, type_="token", max_tries=1):
        txn_receipt = None
        public_key = self.address
        contract_address = Web3.toChecksumAddress(contract_address)
        if type_ == "pair":
            contract = self.w3.eth.contract(contract_address, abi=self.pair_abi)
        elif type_ == "token":
            contract = self.w3.eth.contract(contract_address, abi=self.erc20_abi)
        approved = False
        try:
            approved = contract.functions.allowance(public_key, self.router_address).call()
            if int(approved) <= 500:
                # we have not approved this token yet. approve!
                for _ in range(max_tries):
                    try:
                        txn = contract.functions.approve(
                            self.router_address,
                            115792089237316195423570985008687907853269984665640564039457584007913129639935
                        ).buildTransaction(
                            {
                                'from': public_key, 
                                'gasPrice': self.w3.toWei(self.gas_price, 'gwei'),
                                'nonce': self.get_nonce()
                            }
                        )
                        signed_txn = self.w3.eth.account.sign_transaction(txn, self.private_key)
                        txn = self.w3.eth.sendRawTransaction(signed_txn.rawTransaction)
                        txn_receipt = self.w3.eth.waitForTransactionReceipt(txn)
                        if txn_receipt and "status" in txn_receipt and txn_receipt["status"] == 1: 
                            logging.info('Approved successfully!')
                            approved = True
                            break
                    except:
                        logging.debug(traceback.format_exc())
            else:
                logging.debug('Contract %s already approved.' % contract_address)
                approved = True
        except:
            logging.debug(traceback.format_exc())
        if approved is False:
            logging.debug('Could not approve contract: %s' % contract_address)
        return approved

    def swap_tokens_for_eth(self, token_address, amount, max_tries=1):
        self.approve(token_address, max_tries=max_tries)
        return self._swap_exact_tokens_for_eth(
            eth2wei(amount), 
            self._get_amounts_out(amount, [token_address, self._weth()])[1], 
            [token_address, self._weth()], 
            self.address, 
            int(time.time() + 60), 30, max_tries=max_tries
        )

    def swap_all_tokens_for_tokens(self, from_token_address, to_token_address, max_tries=1):
        # make sure the router is approved to manage this token...
        self.approve(from_token_address, max_tries=max_tries)
        # self.approve(to_token_address)
        account_address = self.address
        # get the total amount of from_token_address in wallet.
        amount_in = self._get_balance(account_address, from_token_address)
        result = None
        if amount_in > 0.0:
            # Now that we have how much we have in our balance we have to let the router
            # adjust the amounts so that swap_exact_tokens_for_tokens() evaluates properly.
            amount_in, amount_out = self._get_amounts_out(amount_in, [from_token_address, to_token_address])
            amount_in = self._fix_decimal(amount_in, token_address=from_token_address)
            amount_out = self._fix_decimal(amount_out, token_address=from_token_address)
            
            logging.info('Swap %s: %s for %s: %s...' % (
                from_token_address, amount_in, to_token_address, amount_out))
            
            # now we can start this party...
            result = self._swap_exact_tokens_for_tokens(
                amount_in, amount_out, [from_token_address, to_token_address], 
                account_address, int(time.time() + 60), 30, max_tries=max_tries)
            if result and "status" in result and result["status"] == 1:
                logging.info('Successfully swapped!')
        else:
            logging.debug('WARNING: Not enough funds.')
        return result
    
    def swap_tokens_for_single_token(self, from_token_address, to_token_address, max_tries=1):
        self.approve(from_token_address, max_tries=max_tries)
        # self.approve(to_token_address)
        account_address = self.address
        # get the amount of from token it costs to get a single to token.
        amount_in, amount_out = self._get_amounts_in(eth2wei(1), [from_token_address, to_token_address])
        normalized_amount_in = self._fix_decimal(amount_in, token_address=from_token_address)
        normalized_amount_out = self._fix_decimal(amount_out, token_address=to_token_address)
        logging.info('Swap %s: %s for %s: %s...' % (
            from_token_address, normalized_amount_in, to_token_address, normalized_amount_out))
        result = self._swap_exact_tokens_for_tokens(eth2wei(normalized_amount_in), eth2wei(normalized_amount_out), 
            [from_token_address, to_token_address], account_address, int(time.time() + 60), 30, max_tries=max_tries)
        if result and "status" in result and result["status"] == 1:
            logging.info('Successfully swapped!')
        return result
        
    def swap_tokens_for_tokens(self, from_token_address, to_token_address, x_amount, max_tries=1):
        # not finished.
        self.approve(from_token_address, max_tries=max_tries)
        # self.approve(to_token_address)
        account_address = self.address
        # get the total amount of X in wallet.
        balance = self._get_balance(account_address, from_token_address)
        result = None
        if balance >= 1.0:
            amount_out, amount_in = self._get_amounts_out(self.eth2wei(x_amount), [to_token_address, from_token_address])
            amount_in = self._fix_decimal(amount_in, token_address=from_token_address)
            amount_out = self._fix_decimal(amount_out, token_address=to_token_address)
            logging.info('amount in: %s' % amount_in)
            logging.info('amount out: %s' % amount_out)
            result = self._swap_exact_tokens_for_tokens(
                eth2wei(amount_in), eth2wei(x_amount), [from_token_address, to_token_address], 
                account_address, int(time.time() + 60), 30, max_tries=max_tries)
            if result and "status" in result and result["status"] == 1:
                logging.info('Successfully swapped!')
        else:
            logging.info('not enough tokens to swap.')
        return result
    
    def add_liquidity(self, tokenA, tokenB, amountA, amountB, txn_timeout, max_tries=1):
        # make sure the router is approved to manage this token...
        pool_address = self.pool_get_address(tokenA, tokenB)
        
        # make sure that tokens and pool are allowed to spend funds.
        self.approve(tokenA, max_tries=max_tries)
        self.approve(tokenB, max_tries=max_tries)
        self.approve(pool_address, type_="pair", max_tries=max_tries)
        
        deadline = int(time.time() + 60)
        account_address = self._get_address()
        
        # get the total amount of from_token_address in wallet.
        tokenA_balance = self._get_balance(account_address, tokenA, max_tries=max_tries)
        tokenB_balance = self._get_balance(account_address, tokenB, max_tries=max_tries)
        
        # make sure user has enough in wallet to provide liquidity.
        if amountA and tokenA_balance < amountA:
            raise Exception("amountA must be less than or equal to your balance.")
        if amountB and tokenB_balance < amountB:
            raise Exception("amountB must be less than or equal to your balance.")
        
        # don't ask me how i figured this shit out. The docs were no help.
        if amountA:
            amountB, amountA_min = self._get_amounts_in(amountA, [tokenB, tokenA], max_tries=max_tries)
            amountA, amountB_min = self._get_amounts_out(amountA, [tokenA, tokenB], max_tries=max_tries)
        else:
            if amountB is None:
                raise Exception("amountA or amountB is required when adding liquidity. None can be used on A or B but not both..")
            amountA, amountB_min = self._get_amounts_in(amountB, [tokenA, tokenB], max_tries=max_tries)
            amountB, amountA_min = self._get_amounts_out(amountB, [tokenB, tokenA], max_tries=max_tries)

        results = self._add_liquidity(
            tokenA, tokenB, amountA, amountB, amountA_min, amountB_min, deadline, txn_timeout, max_tries=max_tries)
            
        if results and "status" in results and results["status"] == 1:
            logging.info("Successfully added liquidity to pool: %s!" % pool_address)
        
        return results
    
    def remove_liquidity_from_pair(self, pair_address, max_tries=1):
        tx_receipt = None
        for _ in range(max_tries):
            try:
                # make sure that tokens and pool are allowed to spend funds.
                pair_contract = self._get_pair_contract(pair_address)
                tokenA = pair_contract.functions.token0().call()
                tokenB = pair_contract.functions.token1().call()
                # make sure that tokens and pool are allowed to spend funds.
                self.approve(tokenA, max_tries=max_tries)
                self.approve(tokenB, max_tries=max_tries)
                self.approve(pair_address, type_="pair", max_tries=max_tries)
                deadline = int(time.time() + 60)
                liquidity = wei2eth(pair_contract.functions.balanceOf(self.address).call())
            except:
                logging.info(traceback.format_exc())
                time.sleep(60)
                continue
            tx_receipt = self._remove_liquidity(
                tokenA, tokenB, eth2wei(liquidity), 1, 1, deadline, max_tries=max_tries)
            if tx_receipt and "status" in tx_receipt and tx_receipt["status"] == 1:
                logging.info('Removed liquidity successfully!')
                break
        return tx_receipt
    
    def get_token_price(self, amount, token, value_token=None):
        if value_token is None:
            value_token = self._weth()
        fixed_token_price = None
        try:
            _, token_price = self._get_amounts_out(amount, [to_checksum(token), to_checksum(value_token)])
            fixed_token_price = self._fix_decimal(token_price, token_address=value_token)
        except:
            logging.debug(traceback.format_exc())
        return fixed_token_price
    
    ### PRIVATE METHODS ###
    
    def _weth(self):
        return self.router_contract.functions.WETH().call()
    
    def _fix_decimal(self, amount, token_address=None, decimals=None):
        if decimals is not None:
            return decimal_fix_places(amount, decimals)
        elif token_address is not None:
            return amount / (10 ** self._get_decimals(token_address))
        else:
            raise Exception("token address, or decimal count must be supplied to _fix_decimal().")
    
    def _link(self, txid):
        return '%s%s' % (self.block_explorer_prefix, str(txid))
    
    def _add_liquidity(self, tokenA, tokenB, amountA, amountB, amountA_min, amountB_min, deadline, max_tries=1):
        
        tokenA_symbol = self._get_symbol(tokenA)
        tokenB_symbol = self._get_symbol(tokenB)
        fixed_amountA = self._fix_decimal(amountA, token_address=tokenA)
        fixed_amountB = self._fix_decimal(amountB, token_address=tokenB)
        
        logging.info('Adding liquidity to %s<>%s. Amounts: %s, %s...' % (
            tokenA_symbol, tokenB_symbol, fixed_amountA, fixed_amountB))
        
        # This was a bitch...
        for _ in range(max_tries):
            try:
                tx = self.router_contract.functions.addLiquidity(
                    tokenA, tokenB, amountA, amountB, amountA_min, amountB_min, self.address, deadline).buildTransaction(
                        {'gasPrice': self.w3.toWei(self.gas_price, 'gwei'), 'nonce': self.get_nonce()})
                logging.debug("Signing transaction")
                signed_tx = self.w3.eth.account.sign_transaction(tx, private_key=self.private_key)
                logging.debug("Sending transaction: %s" % str(signed_tx))
                ret = self.w3.eth.send_raw_transaction(signed_tx.rawTransaction)
                logging.debug("Transaction successfully sent !")
                logging.info(
                    "Waiting for confirmation: " + self._link(signed_tx.hash.hex()))
                tx_receipt = self.w3.eth.wait_for_transaction_receipt(
                    transaction_hash=signed_tx.hash, timeout=self.txn_timeout, poll_latency=3)
                if tx_receipt and "status" in tx_receipt and tx_receipt["status"] == 1:
                    logging.info("Transaction confirmed !")
                    break
            except:
                logging.debug(traceback.format_exc())
                tx_receipt = {"status": 0}
                time.sleep(30)
        return tx_receipt

    def _remove_liquidity(self, tokenA, tokenB, liquidity, amountA_min, amountB_min, deadline, max_tries=1):
        tx_receipt = None
        for _ in range(max_tries):
            token0_symbol = self._get_symbol(tokenA)
            token1_symbol = self._get_symbol(tokenB)
            logging.info('Removing %s LP from %s<>%s...' % (wei2eth(liquidity), token0_symbol, token1_symbol))
            try:
                tx = self.router_contract.functions.removeLiquidity(
                    tokenA, tokenB, liquidity, amountA_min, amountB_min, self.address, deadline).buildTransaction(
                        {'gasPrice': self.w3.toWei(self.gas_price, 'gwei'), 'nonce': self.get_nonce()})
                logging.debug("Signing transaction")
                signed_tx = self.w3.eth.account.sign_transaction(tx, private_key=self.private_key)
                logging.debug("Sending transaction: %s" % str(signed_tx))
                ret = self.w3.eth.send_raw_transaction(signed_tx.rawTransaction)
                logging.debug("Transaction successfully sent !")
                logging.info(
                    "Waiting for confirmation: " + self._link(signed_tx.hash.hex()))
                tx_receipt = self.w3.eth.wait_for_transaction_receipt(
                    transaction_hash=signed_tx.hash, timeout=self.txn_timeout, poll_latency=3)
                if tx_receipt and "status" in tx_receipt and tx_receipt["status"] == 1:
                    logging.info("Transaction confirmed !")
                    break
            except:
                logging.info(traceback.format_exc())
                tx_receipt = {"status": 0}
        return tx_receipt

    def _get_amount_in(self, amount_out, reserve_in, reserve_out, max_tries=1):
        response = None
        for _ in range(max_tries):
            try:
                response = self.router_contract.functions.getAmountIn(
                    amount_out, reserve_in, reserve_out).call()
                if response is not None:
                    break
            except:
                logging.info(traceback.format_exc())
                response = None
        return response
    
    def _get_amount_out(self, amount_in, reserve_in, reserve_out, max_tries=1):
        response = None
        for _ in range(max_tries):
            try:
                response = self.router_contract.functions.getAmountOut(
                    amount_in, reserve_in, reserve_out).call()
                if response is not None:
                    break
            except:
                response = None
                logging.info(traceback.format_exc())
        return response
    
    def _get_amounts_in(self, amount_out, path, max_tries=1):
        response = None
        for _ in range(max_tries):
            try:
                response = self.router_contract.functions.getAmountsIn(
                    amount_out, path).call()
                if response is not None:
                    break
            except:
                logging.info(traceback.format_exc())
        return response
    
    def _get_amounts_out(self, amount_in, path, max_tries=1):
        # this is where we need to handle slippage
        response = None
        for _ in range(max_tries):
            try:
                response = self.router_contract.functions.getAmountsOut(
                    amount_in,
                    path
                ).call()
                if response is not None:
                    break
            except:
                logging.info(traceback.format_exc())
        return response
    
    def _get_symbol(self, token_address, max_tries=1):
        contract = self.w3.eth.contract(Web3.toChecksumAddress(token_address), abi=self.erc20_abi)
        response = None
        for _ in range(max_tries):
            try:
                response = contract.functions.symbol().call()
                if response is not None:
                    break
            except:
                logging.info(traceback.format_exc())
        return response
    
    def _get_name(self, token_address, max_tries=1):
        contract = self.w3.eth.contract(Web3.toChecksumAddress(token_address), abi=self.erc20_abi)
        for _ in range(max_tries):
            try:
                response = contract.functions.name().call()
                if response is not None:
                    break
            except:
                logging.info(traceback.format_exc())
        return response
    
    def _get_decimals(self, token_address, max_tries=1):
        contract = self.w3.eth.contract(Web3.toChecksumAddress(token_address), abi=self.erc20_abi)
        response = None
        for _ in range(max_tries):
            try:
                response = contract.functions.decimals().call()
                if response is not None:
                    break
            except:
                logging.info(traceback.format_exc())
    
    def _get_balance(self, address, token_address, max_tries=1):
        contract = self.w3.eth.contract(Web3.toChecksumAddress(token_address), abi=self.erc20_abi)
        response = None
        for _ in range(max_tries):
            try:
                response = contract.functions.balanceOf(address).call()
                if response is not None:
                    break
            except:
                logging.info(traceback.format_exc())
        return response
    
    def _get_token_contract(self, token_address):
        return self.w3.eth.contract(Web3.toChecksumAddress(token_address), abi=self.erc20_abi)
    
    def _get_pair_contract(self, pair_address):
        return self.w3.eth.contract(
            to_checksum(pair_address), abi=self.pair_abi)
    
    def _weth(self):
        return self.router_contract.functions.WETH().call()
    
    def _quote(self, amount_a, reserve_a, reserve_b, max_tries=1):
        response = None
        for _ in range(max_tries):
            try:
                response = self.router_contract.functions.quote(amount_a, reserve_a, reserve_b).call()
                if response is not None:
                    break
            except:
                logging.info(traceback.format_exc())
        return response
    
    def _swap_exact_tokens_for_tokens(self, amount_in, amount_out_min, path, to, deadline, max_tries=1):
        tx_receipt = None
        for _ in range(max_tries):
            try:
                tx = self.router_contract.functions.swapExactTokensForTokens(
                    amount_in, amount_out_min, path, to, deadline).buildTransaction(
                    {'gasPrice': self.w3.toWei(self.gas_price, 'gwei'), 
                    'nonce': self.get_nonce()})
                logging.debug("Signing transaction")
                signed_tx = self.w3.eth.account.sign_transaction(tx, private_key=self.private_key)
                logging.debug("Sending transaction " + str(tx))
                ret = self.w3.eth.send_raw_transaction(signed_tx.rawTransaction)
                logging.debug("Transaction successfully sent !")
                logging.info(
                    "Waiting for confirmation: " + self._link(signed_tx.hash.hex()))
                tx_receipt = self.w3.eth.wait_for_transaction_receipt(
                    transaction_hash=signed_tx.hash, timeout=self.txn_timeout, poll_latency=3)
                if tx_receipt and "status" in tx_receipt and tx_receipt["status"] == 1:
                    logging.info("Transaction confirmed !")
                    break
                else:
                    logging.info('Could not perform swap.')
                    time.sleep(60)
            except:
                logging.debug(traceback.format_exc())
        return tx_receipt
    
    def _swap_exact_tokens_for_eth(self, amount_in, amount_out_min, path, to, deadline, max_tries=1):
        for _ in range(max_tries):
            try:
                tx = self.router_contract.functions.swapExactTokensForETH(amount_in, amount_out_min, path, to, deadline).buildTransaction(
                    {'gasPrice': self.w3.toWei(self.gas_price, 'gwei'), 'nonce': self.get_nonce()})
                logging.debug("Signing transaction")
                signed_tx = self.w3.eth.account.sign_transaction(tx, private_key=self.private_key)
                logging.debug("Sending transaction " + str(tx))
                ret = self.w3.eth.send_raw_transaction(signed_tx.rawTransaction)
                logging.debug("Transaction successfully sent !")
                logging.info(
                    "Waiting for confirmation: " + self._link(signed_tx.hash.hex()))
                tx_receipt = self.w3.eth.wait_for_transaction_receipt(
                    transaction_hash=signed_tx.hash, timeout=self.txn_timeout, poll_latency=3)
                if tx_receipt and "status" in tx_receipt and tx_receipt["status"] == 1:
                    logging.info("Transaction confirmed !")
                    break
            except:
                logging.debug(traceback.format_exc())
        return tx_receipt
    
    def _get_pair_address(self, token_address_1, token_address_2):
        return self.factory_contract.functions.getPair(
            to_checksum(token_address_1), to_checksum(token_address_2)).call()
    
    def _get_pair_length(self, max_tries=1):
        response = None
        for _ in range(max_tries):
            try:
                response = self.factory_contract.functions.allPairsLength().call()
                if response is not None:
                    break
            except:
                logging.info(traceback.format_exc())
        return response
    
    def _get_pair_index(self, index, max_tries=1):
        response = None
        for _ in range(max_tries):
            try:
                response = self.factory_contract.functions.allPairs(index).call()
                if response is not None:
                    break
            except:
                logging.info(traceback.format_exc())
        return response
    
    def _get_all_pairs(self, max_tries=1):
        pairs = []
        for i in range(self._get_pair_length(max_tries=max_tries)):
            result = self._get_pair_index(i, max_tries=max_tries)
            if result is not None:
                pairs.append(result)
        return pairs
    
    def _get_deposited_pairs(self, max_tries=1):
        pairs = []
        logging.info('Looking for deposited liquidity pools...')
        for i in range(self._get_pair_length(max_tries=max_tries)):
            pair_address = self._get_pair_index(i, max_tries=max_tries)
            pair_contract = self._get_pair_contract(pair_address)
            lp_balance = wei2eth(pair_contract.functions.balanceOf(self.address).call())
            if lp_balance > 0.0:
                logging.info('Found %s with %s LP tokens!' % (pair_address, lp_balance))
                pairs.append(self._get_pair_index(i, max_tries=max_tries))
        return pairs
    
    def _get_pool_info(self, pair_address, value_token=None, max_tries=3):
        result = {}
        for _ in range(max_tries):
            try:
                if value_token is None:
                    value_token = self._weth()
                pair_contract = self._get_pair_contract(pair_address)
                reserves = pair_contract.functions.getReserves().call()
                pair_balance = pair_contract.functions.balanceOf(self.address).call()
                total_supply = pair_contract.functions.totalSupply().call()
                token0 = pair_contract.functions.token0().call()
                token1 = pair_contract.functions.token1().call()
                token0_contract = self._get_token_contract(token0)
                token1_contract = self._get_token_contract(token1)
                token0_decimals = token0_contract.functions.decimals().call()
                token1_decimals = token1_contract.functions.decimals().call()
                token0_name = token0_contract.functions.symbol().call()
                token1_name = token1_contract.functions.symbol().call()
                
                # fix the decimals to the correct places.
                # DO NOT USE fromWei()!
                reserves[0] = self._fix_decimal(reserves[0], decimals=token0_decimals)
                reserves[1] = self._fix_decimal(reserves[1], decimals=token1_decimals)
                
                total_supply = Web3.fromWei(total_supply, "ether")
                pair_balance = Web3.fromWei(pair_balance, "ether")
                
                # Find the amount for both sides of the pair.
                token0_pool_amount = Decimal(pair_balance) / (Decimal(total_supply) / Decimal(reserves[0]))
                token1_pool_amount = Decimal(pair_balance) / (Decimal(total_supply) / Decimal(reserves[1]))
                
                logging.debug('reserves: %s' % reserves)
                logging.debug('total supply: %s' % total_supply)
                logging.debug('pair_balance: %s.' % pair_balance)
                logging.debug('amount0: %s' % token0_pool_amount)
                logging.debug('amount1: %s' % token1_pool_amount)
                
                if str(token0) != str(value_token):
                    token0_value = Web3.fromWei(self._get_amounts_out(1, [token0, value_token])[1], "ether") * token0_pool_amount
                else:
                    token0_value = token0_pool_amount
                
                if str(token1) != str(value_token):
                    token1_value = Web3.fromWei(self._get_amounts_out(1, [token1, value_token])[1], "ether") * token1_pool_amount
                else:
                    token1_value = token1_pool_amount
                
                total_value = token1_value + token0_value
                
                result = {
                    "reserves": reserves,
                    "token0": token0,
                    "token1": token1,
                    "token0_name": token0_name,
                    "token1_name": token1_name,
                    "symbol": "%s<>%s" % (token0_name, token1_name),
                    "token0_amount": token0_pool_amount,
                    "token1_amount": token1_pool_amount,
                    "total_value": total_value
                }
                break
            except:
                logging.debug(traceback.format_exc())
                return None
        return result

    