# denaro

**denaro**, _'money' in italian_, is a cryptocurrency written in Python.  
Maximum supply is 30.062.005.  
Maximum decimal digits count is 6.  
Blocks are generated every ~3 minutes, with a limit of 1000 transactions per block, and a limit of 2048 bytes per transaction.  
This makes possible to handle ~5 transactions per second, with a maximum block size of 2000kb.  

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
psql -d denaro
## paste content of schema.sql
```

Then install denaro.  

```bash
git clone https://github.com/denaro-coin/denaro
cd denaro
pip3 install -r requirements.txt
uvicorn denaro.node.main:app --port 3006 --workers 2
```

Node should now sync the blockchain and start working


## Mining

denaro uses a PoW system.  

Block hash is the sha256 of raw bytes of `previous_hash, public_key, merkle_tree, timestamp, difficulty, random`, for example `387389eb614db0e3ada0af248f2f0adac12db35963f4bbdd71ef14914e8ade81dbda85e237b90aa669da00f2859e0010b0a62e0fb6e55ba6ca3ce8a961a60c64410bcfb6a038310a3bb6f1a4aaa2de1192cc10e380a774bb6f9c6ca8547f11abe3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b8556662796132007d521100`  
The derived sha256 must start with the last `difficulty` characters (hex) of the previous mined block.  
`random` must be at most 4 bytes long.  
`difficulty` can also have decimal digits (in block it is in fact `difficulty * 10`, 2 bytes long), that will restrict the `difficulty + 1`th character of the derived sha to have a limited set of values.  
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
