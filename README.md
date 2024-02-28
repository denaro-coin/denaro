# Denaro

**Denaro** is a cryptocurrency developed in Python, named for the Italian word for 'money'. It features a maximum supply of 30,062,005 and allows for transactions with up to 6 decimal places. Blocks are generated approximately every ~3 minutes, with a limit of 2MB per block. Given an average transaction size of 250 bytes (comprising 5 inputs and 2 outputs), a block can accommodate approximately ~8300 transactions, which translates to about ~40 transactions per second.

## Setup with Docker

```bash
make build
docker-compose up -d
```

## Installation

```bash
git clone https://github.com/denaro-coin/denaro
cd denaro
sudo bash db_setup.sh
pip3 install -r requirements.txt
uvicorn denaro.node.main:app --port 3006
```

## Sync Blockchain

To synchronize a node with the Denaro blockchain, send a GET request to the `/sync_blockchain` endpoint after starting your node:

```bash
curl http://localhost:3006/sync_blockchain
```

## Mining

**Denaro** adopts a Proof of Work (PoW) system for its mining process:

- **Block Hashing**:
  - Utilizes the sha256 algorithm for block hashing.
  - The hash of a block must begin with the last `difficulty` hexadecimal characters of the hash from the previously mined block.
  - `difficulty` can also have decimal digits, that will restrict the difficulty + 1th character of the derived sha to have a limited set of values.

    ```python
    from math import ceil

    difficulty = 6.3
    decimal = difficulty % 1

    charset = '0123456789abcdef'
    count = ceil(16 * (1 - decimal))
    allowed_characters = charset[:count]
    ```

- **Rewards**:
  - Block rewards decrease by half over time until they reach zero.
  - Rewards start at `100` for the initial `150,000` blocks, decreasing in predetermined steps until a final reward of `0.3125` for the `458,733`rd block.
  - After this, blocks do not offer a mining reward, but transaction fees are still applicable. A transaction may also have no fees at all.
