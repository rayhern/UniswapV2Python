# UniswapV2Python

# By: Ray Hernandez.

Please show me support by signing up under me at theanimal.farm, or at drip.community.

```
Here are my referral links:
https://theanimal.farm/referrals/0x07FBc81988EaDF3C3126D354838F3B899BF3377A

https://drip.community/faucet?buddy=0x07FBc81988EaDF3C3126D354838F3B899BF3377A

If you want to send me some crypto for helping you out with your drip garden, and web3 please do to the following address:
0x07FBc81988EaDF3C3126D354838F3B899BF3377A

Anything you can do is much appreciated. Hit me up on twitter if you have any questions. twitter.com/bizong

```

This is a UniswapV2 class i wrote in python to handle swapping functions and liquidity providing. I also included a liquidity watcher script
that will use the custom UniswapV2 class I made to watch liquidity and remove liquidity when the overall value of the liquidity is a percent
X above or below the price when the script started. This is extremely useful considering there are no options on Uniswap's smart contracts
to do this. Copy settings.py.example to settings.py and adjust your settings in that file.

Python3.6+ Required!

To install:

`pip install --upgrade setuptools wheel pip`

`pip install -r requirements.txt`

To setup (copy settings.py.example to settings.py):
`cp settings.py.example settings.py`

After you adjust your settings.py, make sure you add your private key to the settings from Metamask.

To use:
`python liquidity.py`
