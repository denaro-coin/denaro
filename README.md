# Denaro

## Overview

**Denaro**, 'money' in Italian, is a cryptocurrency developed entirely in Python and utilizes PostgreSQL for it's blockchain.

* **Features**: 
  * Maximum supply of 30,062,005 coins.
  * Allows for transactions with up to 6 decimal places.
  * Blocks are generated approximately every ~3 minutes, with a limit of 2MB per block.
  * Given an average transaction size of 250 bytes (comprising of 5 inputs and 2 outputs), a single block can accommodate approximately ~8300 transactions, which translates to about ~40 transactions per second.

## Installation

Automated configuration and deployment of a Denaro node are facilitated by `setup.sh`. This script handles the installation of necessary libraries, setup of PostgreSQL, Python virtual environment, and other prerequisites required for running a Denaro node. 

*For those who wish to only set up the PostgreSQL database, a `db_setup.sh` script is provided. This script focuses solely on preparing the PostgreSQL database for Denaro's blockchain.*

* Execute the commands below to initiate the installation:


  ```bash
  # Clone the Denaro repository to your local machine.
  git clone https://github.com/denaro-coin/denaro
  
  # Change directory to the cloned repository.
  cd denaro
  
  # Make the setup script executable.
  chmod +x setup.sh
  
  # Execute the setup script.
  ./setup.sh
  ```

* For PostgreSQL setup only:

  ```bash
  chmod +x db_setup.sh
  ./db_setup.sh
  ```

## Running a Denaro Node

A Denaro node can be started manually if you have already executed the `setup.sh` script and chose not to start the node immediately, or if you need to start the node in a new terminal session. 

*Note: Users who opted to use the `db_setup.sh` script should set up a Python virtual environment (optional) and install the Python packages from `requirements.txt` prior to starting the node.*

Execute the commands below to manually start a Denaro node:

```bash
# Navigate to the Denaro directory.
cd path/to/denaro

# For users who executed db_setup.sh: 
# Set up the Python virtual environment (Optional but recommended).
sudo apt install python3-venv
python3 -m venv venv
source venv/bin/activate

# Install the required packages if needed.
pip install -r requirements.txt

# Manualy start the Denaro node on port 3006 or another specified port.
uvicorn denaro.node.main:app --port 3006

# To stop the node, press Ctrl+C in the terminal.
```
To exit the Python virtual environment, use the command:

```bash
deactivate
```

## Setup with Docker

```bash
make build
docker-compose up -d
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
