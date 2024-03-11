# Denaro

## Overview

**Denaro**, 'money' in Italian, is a cryptocurrency developed entirely in Python and utilizes PostgreSQL for it's blockchain.

* **Features**: 
  * Maximum supply of 30,062,005 coins.
  * Allows for transactions with up to 6 decimal places.
  * Blocks are generated approximately every ~3 minutes, with a limit of 2MB per block.
  * Given an average transaction size of 250 bytes (comprising of 5 inputs and 2 outputs), a single block can accommodate approximately ~8300 transactions, which translates to about ~40 transactions per second.

## Installation

**Automated configuration and deployment of a Denaro node are facilitated by the `setup.sh` script. It handles system package updates, configures the PostgreSQL database, sets up a Python virtual environment, installs the required Python dependencies, and initiates the Denaro node. This script ensures that all prerequisites for operating a Denaro node are met and properly configured accoring to the user's preference.**
 
- The setup script accepts three optional arguments to adjust its behavior during installation:

  - `--skip-prompts`: Executes the setup script in an automated manner without requiring user input, bypassing all interactive prompts.
  
  - `--setup-db`: Limits the setup script's actions to only configure the PostgreSQL database, excluding the execution of other operations such as virtual environment setup and dependency installation.

  - `--skip-package-install`: Skips APT package installation. This can be used for Linux distributions that do not use APT as a package manager. However, it is important that the required system packages are installed prior to using the setup script in order for it to work corectly.

**Execute the commands below to initiate the installation:**

  ```bash
  # Clone the Denaro repository to your local machine.
  git clone https://github.com/The-Sycorax/denaro
  
  # Change directory to the cloned repository.
  cd denaro
  
  # Make the setup script executable.
  chmod +x setup.sh
  
  # Execute the setup script with optional arguments as needed.
  ./setup.sh [--skip-prompts] [--setup-db] [--skip-package-install]
  ```

***Note:** The setup script is designed for Linux distributions that utilize `apt` as their package manager (e.g. Debian/Ubuntu). If system package installation is unsuccessful, it may be due to the absence of 'apt' on your system. In which case, the required system packages must be installed manually. Below you will find a list of the required system packages.*

<details>
<summary><i>Required Packages:</i></summary>
<dl><dd>

*It is nessessary to ensure that the package names specified are adjusted to correspond with those recognized by your package manager.*

- `postgresql`
- `libgmp-dev`
- `libpq-dev`
- `python3-venv` (If using a python virtual environment)
 
</dd></dl>
</details>

*Once the required packages have been installed, the `--skip-package-install` argument can be used with the setup script to bypass operations which require 'apt', thus mitigating any unsucessful execution relating to package installation.*

## Running a Denaro Node

A Denaro node can be started manually if you have already executed the `setup.sh` script and chose not to start the node immediately, or if you need to start the node in a new terminal session. 

***Note:** Users who have used the setup script with the `--setup-db` argument or have performed a manual installation, should create a Python virtual environment (Optional) and ensure that the required Python packages are installed prior to starting a node.*

Execute the commands below to manually start a Denaro node:

```bash
# Navigate to the Denaro directory.
cd path/to/denaro

# Set up a Python virtual environment (Optional but recommended).
sudo apt install python3-venv
python3 -m venv venv
source venv/bin/activate

# Install the required packages if needed.
pip install -r requirements.txt

# Manualy start the Denaro node on port 3006 or another specified port.
uvicorn denaro.node.main:app --port 3006

# To stop the node, press Ctrl+C in the terminal.
```

To exit a Python virtual environment, use the command:

```bash
deactivate
```

## Setup with Docker

```bash
make build
docker-compose up -d
```

## Sync Blockchain

To synchronize a node with the Denaro blockchain, send a request to the `/sync_blockchain` endpoint after starting your node:

```bash
curl http://localhost:3006/sync_blockchain
```

## Mining

**Denaro** adopts a Proof of Work (PoW) system for its mining process:

- **Block Hashing**:
  - Utilizes the sha256 algorithm for block hashing.
  - The hash of a block must begin with the last `difficulty` hexadecimal characters of the hash from the previously mined block.
  - `difficulty` can also have decimal digits, that will restrict the `difficulty + 1`st character of the derived sha to have a limited set of values.

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
