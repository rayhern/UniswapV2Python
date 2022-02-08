from web3 import Web3
from decimal import Decimal, getcontext
import traceback
import time
import logging

ROUTER_ABI_FILE = "./abi/UniswapV2Router.json"
PAIR_ABI_FILE = "./abi/UniswapV2Pair.json"
FACTORY_ABI_FILE = "./abi/UniswapV2Factory.json"
ERC20_ABI_FILE = "./abi/ERC20.json"

def wei2eth(wei, unit="ether"):
    return Web3.fromWei(wei, unit)

def eth2wei(eth, unit="ether"):
    return Web3.toWei(eth, unit)

def to_checksum(address):
    return Web3.toChecksumAddress(address)

def read_json_file(filepath):
    try:
        with open(filepath) as fp:
            results = fp.read()
    except:
        logging.info('Error reading json file.')
        results = None
    return results

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
        return self.w3.eth.getTransactionCount(self.address)

    def swap_tokens_for_eth(self, token_address, amount):
        self.approve(token_address)
        return self._swap_exact_tokens_for_eth(
            eth2wei(amount), 
            self._get_amounts_out(amount, [token_address, self._weth()])[1], 
            [token_address, self._weth()], 
            self.address, 
            int(time.time() + 60), 30
        )
    
    def approve(self, contract_address, type_="token"):
        txn_receipt = None
        public_key = self.address
        contract_address = Web3.toChecksumAddress(contract_address)
        if type_ == "pair":
            contract = self.w3.eth.contract(contract_address, abi=self.pair_abi)
        elif type_ == "token":
            contract = self.w3.eth.contract(contract_address, abi=self.erc20_abi)
        approved = contract.functions.allowance(
            public_key, self.router_address).call()
        if int(approved) <= 500:
            # we have not approved this token yet. approve!
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
            signed_txn = self.w3.eth.account.sign_transaction(
                txn, self.private_key)
            txn = self.w3.eth.sendRawTransaction(signed_txn.rawTransaction)
            txn_receipt = self.w3.eth.waitForTransactionReceipt(txn)
            if txn_receipt and "status" in txn_receipt and txn_receipt["status"] == 1: 
                logging.info('Approved successfully!')
            else:
                logging.info('Could not approve contract: %s' % contract_address)
        return txn_receipt

    def swap_all_tokens_for_tokens(self, from_token_address, to_token_address):
        # make sure the router is approved to manage this token...
        self.approve(from_token_address)
        self.approve(to_token_address)
        account_address = self.address
        # get the total amount of from_token_address in wallet.
        amount_in = self._get_balance(account_address, from_token_address)
        result = None
        if amount_in > 0.0:
            # Now that we have how much we have in our balance we have to let the router
            # adjust the amounts so that swap_exact_tokens_for_tokens() evaluates properly.
            amounts = self._get_amounts_out(amount_in, [from_token_address, to_token_address])
            amount_in, amount_out = amounts
            logging.info('Swap %s: %s for %s: %s...' % (
                from_token_address, wei2eth(amount_in), to_token_address, wei2eth(amount_out)))
            
            # now we can start this party...
            try:
                result = self._swap_exact_tokens_for_tokens(
                    amount_in, amount_out, [from_token_address, to_token_address], 
                    account_address, int(time.time() + 60), 30)
            except:
                result = {"status": 0}
                logging.info("EXCEPTION: %s" % traceback.format_exc())
            if result["status"] == 1:
                logging.info('Successfully swapped!')
                return True
        else:
            logging.debug('WARNING: Not enough funds.')
        return False
    
    def swap_tokens_for_single_token(self, from_token_address, to_token_address):
        self.approve(from_token_address)
        self.approve(to_token_address)
        account_address = self.address
        # get the amount of from token it costs to get a single to token.
        amounts = self._get_amounts_in(eth2wei(1), [from_token_address, to_token_address])
        # amounts = self._get_amounts_out(self.eth2wei(amount_in), [from_token_address, to_token_address])
        amount_in, amount_out = amounts
        logging.info('Swap %s: %s for %s: %s...' % (
            from_token_address, wei2eth(amount_in), to_token_address, wei2eth(amount_out)))
        # logging.info('amount out: %s' % self.wei2eth(amounts[1]))
        try:
            result = self._swap_exact_tokens_for_tokens(
                amount_in, amount_out, [from_token_address, to_token_address], 
                account_address, int(time.time() + 60), 30)
        except:
            result = {"status": 0}
        if result["status"] == 1:
            logging.info('Successfully swapped!')
            return True
        else:
            return False
        
    def swap_tokens_for_tokens(self, from_token_address, to_token_address, x_amount):
        # not finished.
        self.approve(from_token_address)
        self.approve(to_token_address)
        account_address = self.address
        # get the total amount of X in wallet.
        balance = self._get_balance(account_address, from_token_address)
        result = None
        if balance >= 1.0:
            amount_in = self._get_amounts_out(self.eth2wei(x_amount), [to_token_address, from_token_address])[1]
            amount_in = wei2eth(amount_in)
            logging.info('amount in: %s' % amount_in)
            
            # result = self.router.swap_exact_tokens_for_tokens(
            #     self.hrc20.eth2wei(amount_in), self.hrc20.eth2wei(x_amount), [from_token_address, to_token_address], 
            #     account_address, int(time.time() + 60), 30)
        else:
            logging.info('not enough tokens to swap.')
        return result
    
    def add_liquidity(self, tokenA, tokenB, amountA, amountB, txn_timeout):
        # make sure the router is approved to manage this token...
        pool_address = self.pool_get_address(tokenA, tokenB)
        
        # make sure that tokens and pool are allowed to spend funds.
        self.approve(tokenA)
        self.approve(tokenB)
        self.approve(pool_address, contract_type="pair")
        
        deadline = int(time.time() + 60)
        account_address = self._get_address()
        
        # get the total amount of from_token_address in wallet.
        tokenA_balance = self._get_balance(account_address, tokenA)
        tokenB_balance = self._get_balance(account_address, tokenB)
        
        # make sure user has enough in wallet to provide liquidity.
        if amountA and tokenA_balance < amountA:
            raise Exception("amountA must be less than or equal to your balance.")
        if amountB and tokenB_balance < amountB:
            raise Exception("amountB must be less than or equal to your balance.")
        
        # don't ask me how i figured this shit out. The docs were no help.
        if amountA:
            amountB, amountA_min = self._get_amounts_in(amountA, [tokenB, tokenA])
            amountA, amountB_min = self._get_amounts_out(amountA, [tokenA, tokenB])
        else:
            if amountB is None:
                raise Exception("DefiKingdoms Exception: amountA or amountB is required when adding liquidity. None can be used on A or B but not both..")
            amountA, amountB_min = self._get_amounts_in(amountB, [tokenA, tokenB])
            amountB, amountA_min = self._get_amounts_out(amountB, [tokenB, tokenA])

        try:
            results = self._add_liquidity(
                tokenA, tokenB, amountA, amountB, amountA_min, amountB_min, deadline, txn_timeout)
        except:
            logging.info(traceback.format_exc())
            results = None
            
        if results["status"] == 1:
            logging.info("Successfully added liquidity to pool: %s!" % pool_address)
            return True
        else:
            return False
    
    def remove_all_liquidity(self, pair_address):
        # make sure that tokens and pool are allowed to spend funds.
        pair_contract = self._get_pair_contract(pair_address)
        tokenA = pair_contract.functions.token0().call()
        tokenB = pair_contract.functions.token1().call()
        # make sure that tokens and pool are allowed to spend funds.
        self.approve(tokenA)
        self.approve(tokenB)
        self.approve(pair_address, contract_type="pair")
        deadline = int(time.time() + 60)
        liquidity = pair_contract.functions.balanceOf(self.address).call()
        reserves = pair_contract.functions.getReserves().call()
        total_supply = pair_contract.functions.totalSupply().call()
        amountA = liquidity / (total_supply / reserves[0])
        # amountB = liquidity / (total_supply / reserves[1])
        _, amountA_min = self._get_amounts_in(amountA, [tokenB, tokenA])
        _, amountB_min = self._get_amounts_out(amountA, [tokenA, tokenB])
        try:
            tx_receipt = self._remove_liquidity(
                tokenA, tokenB, liquidity, amountA_min, amountB_min, deadline)
            if tx_receipt and "status" in tx_receipt and tx_receipt["status"] == 1:
                return True
        except:
            logging.info(traceback.format_exc())
            tx_receipt = {"status": 0}
        return False
    
    ### PRIVATE METHODS ###
    
    def _link(self, txid):
        return '%s%s' % (self.block_explorer_prefix, str(txid))
    
    def _add_liquidity(self, tokenA, tokenB, amountA, amountB, amountA_min, amountB_min, deadline):
        
        tokenA_symbol = self._get_symbol(tokenA)
        tokenB_symbol = self._get_symbol(tokenB)
        
        logging.info('Adding liquidity to %s<>%s. Amounts: %s, %s...' % (
            tokenA_symbol, tokenB_symbol, wei2eth(amountA), wei2eth(amountB)))
        
        # This was a bitch...
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
        except:
            logging.info(traceback.format_exc())
            tx_receipt = {"status": 0}
        return tx_receipt

    def _remove_liquidity(self, tokenA, tokenB, liquidity, amountA_min, amountB_min, deadline):
        token0_symbol = self._get_symbol(tokenA)
        token1_symbol = self._get_symbol(tokenB)
        logging.info('Removing %s LP from %s<>%s...' % (round(liquidity, 8), token0_symbol, token1_symbol))
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
        except:
            logging.info(traceback.format_exc())
            tx_receipt = {"status": 0}
        return tx_receipt

    def _get_amount_in(self, amount_out, reserve_in, reserve_out):
        return self.router_contract.functions.getAmountIn(amount_out, reserve_in, reserve_out).call()
    
    def _get_amount_out(self, amount_in, reserve_in, reserve_out):
        return self.router_contract.functions.getAmountOut(amount_in, reserve_in, reserve_out).call()
    
    def _get_amounts_in(self, amount_out, path):
        return self.router_contract.functions.getAmountsIn(amount_out, path).call()
    
    def _get_amounts_out(self, amount_in, path):
        # this is where we need to handle slippage
        return self.router_contract.functions.getAmountsOut(
            amount_in,
            path
        ).call()
    
    def _get_symbol(self, token_address):
        contract_address = Web3.toChecksumAddress(token_address)
        contract = self.w3.eth.contract(contract_address, abi=self.erc20_abi)
        return contract.functions.symbol().call()
    
    def _get_name(self, token_address):
        contract_address = Web3.toChecksumAddress(token_address)
        contract = self.w3.eth.contract(contract_address, abi=self.erc20_abi)
        return contract.functions.name().call()
    
    def _get_decimals(self, token_address):
        contract_address = Web3.toChecksumAddress(token_address)
        contract = self.w3.eth.contract(contract_address, abi=self.erc20_abi)
        return contract.functions.decimals().call()
    
    def _get_balance(self, address, token_address):
        contract_address = Web3.toChecksumAddress(token_address)
        contract = self.w3.eth.contract(contract_address, abi=self.erc20_abi)
        return contract.functions.balanceOf(address).call()
    
    def _get_token_contract(self, token_address):
        contract_address = Web3.toChecksumAddress(token_address)
        contract = self.w3.eth.contract(contract_address, abi=self.erc20_abi)
        return contract
    
    def _get_pair_contract(self, pair_address):
        return self.w3.eth.contract(
            to_checksum(pair_address), abi=self.pair_abi)
    
    def _weth(self):
        return self.router_contract.functions.WETH().call()
    
    def _quote(self, amount_a, reserve_a, reserve_b):
        return self.router_contract.functions.quote(amount_a, reserve_a, reserve_b).call()
    
    def _swap_exact_tokens_for_tokens(self, amount_in, amount_out_min, path, to, deadline):
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
        return tx_receipt
    
    def _swap_exact_tokens_for_eth(self, amount_in, amount_out_min, path, to, deadline, tx_timeout_seconds):
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
        return tx_receipt
    
    def _get_pair_address(self, token_address_1, token_address_2):
        return self.factory_contract.functions.getPair(
            to_checksum(token_address_1), to_checksum(token_address_2)).call()
    
    def _get_pair_length(self):
        return self.factory_contract.functions.allPairsLength().call()
    
    def _get_pair_index(self, index):
        return self.factory_contract.functions.allPairs(index).call()
    
    def _get_all_pairs(self):
        pairs = []
        for i in range(self._get_pair_length()):
            pairs.append(self._get_pair_index(i))
        return pairs
    
    def _get_deposited_pairs(self):
        pairs = []
        logging.info('Looking for deposited liquidity pools...')
        for i in range(self._get_pair_length()):
            pair_address = self._get_pair_index(i)
            pair_contract = self._get_pair_contract(pair_address)
            lp_balance = wei2eth(pair_contract.functions.balanceOf(self.address).call())
            if lp_balance > 0.0:
                logging.info('Found %s with %s LP tokens!' % (pair_address, lp_balance))
                pairs.append(self._get_pair_index(i))
        return pairs
    
    def _get_pool_info(self, pair_address, value_token=None):
        if value_token is None:
            value_token = self._weth()
        try:
            pair_contract = self._get_pair_contract(pair_address)
            reserves = pair_contract.functions.getReserves().call()
            pair_balance = pair_contract.functions.balanceOf(self.address).call()
            total_supply = pair_contract.functions.totalSupply().call()
            token0 = pair_contract.functions.token0().call()
            token1 = pair_contract.functions.token1().call()
            token0_contract = self._get_token_contract(token0)
            token1_contract = self._get_token_contract(token1)
            token0_name = token0_contract.functions.symbol().call()
            token1_name = token1_contract.functions.symbol().call()
        except:
            logging.info(traceback.format_exc())
            return None
        
        token0_pool_amount = Decimal(pair_balance / (total_supply / reserves[0]))
        token1_pool_amount = Decimal(pair_balance / (total_supply / reserves[1]))

        if str(token0) != value_token:
            token0_value = Web3.fromWei(self._get_amounts_out(1, [token0, value_token])[1], "ether") * Decimal(token0_pool_amount)
        else:
            token0_value = Web3.fromWei(token0_pool_amount, "ether")
        
        if str(token1) != value_token:
            token1_value = Web3.fromWei(self._get_amounts_out(1, [token1, value_token])[1], "ether") * Decimal(token1_pool_amount)
        else:
            token1_value = Web3.fromWei(token1_pool_amount, "ether")
        
        total_value = Decimal(0.0)
        total_value += token0_value
        total_value += token1_value
        
        token1_pool_amount = Web3.fromWei(token1_pool_amount, "ether")

        return {
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

    