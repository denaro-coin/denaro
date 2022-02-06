denaro
======

**denaro**, _'money' in italian_, is a cryptocurrency written in Python.  
Maximum supply is 30.062.005.  
Maximum decimal digits count is 6.  
Blocks are generated every ~3 minutes, with a size limit of 2MB per block.  
Assuming an average transaction to be composed by 5 inputs and 2 outputs, that are 250 bytes, a block can contain ~8300 transactions, which means ~40 transactions per second.    

## Setup with Docker
+ Build the base image with `make build`
+ `$ docker-compose up -d`

## Installation

Before installing denaro, you need to create the postgresql database.  
You can find the schema in [schema.sql](schema.sql).  
You have to set environmental variables for database access:
- `DENARO_DATABASE_USER`, default to `denaro`.  
- `DENARO_DATABASE_PASSWORD`, default to an empty string.  
- `DENARO_DATABASE_NAME`, default to `denaro`.  
- `DENARO_DATABASE_HOST`, default to `127.0.0.1`.  


```bash
# install postgresql
createdb denaro
```

Then install denaro.  

```bash
git clone https://github.com/denaro-coin/denaro
cd denaro
psql -d denaro -f schema.sql
pip3 install -r requirements.txt
uvicorn denaro.node.main:app --port 3006
```

Node should now sync the blockchain and start working


## Mining

denaro uses a PoW system.  

Block hash algorithm is sha256.  
The block sha256 hash must start with the last `difficulty` hex characters of the previously mined block.    
`difficulty` can also have decimal digits, that will restrict the `difficulty + 1`th character of the derived sha to have a limited set of values.    
```python
from math import ceil

difficulty = 6.3
decimal = difficulty % 1

charset = '0123456789abcdef'
count = ceil(16 * (1 - decimal))
allowed_characters = charset[:count]
```

Address must be present in the string in order to ensure block property.  

Blocks have a block reward that will half itself til it reaches 0.  
There will be `150000` blocks with reward `100`, and so on til `0.390625`, which will last `458732` blocks.   
The last block with a reward will be the `458733`th, with a reward of `0.3125`.  
Subsequent blocks won't have a block reward.  
Reward will be added the fees of the transactions included in the block.  
A transaction may also have no fees at all.  
