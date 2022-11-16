## Full node installation procedure (linux)

Running a node is only possible on Linux-based OS or macOS.
To run a node on your machine, you will need to install PostgreSQL 14.
In this guide, no password will be set for the database and no "denaro" role will be created.
<br>

First of all, install the necessary packages.
```bash
# Install necessary packages & upgrade the system
sudo apt update && sudo apt upgrade
sudo apt -y install gnupg2 wget
```

Add the PostgreSQL repo in your system.
```bash
# Add the PostgreSQL repo to the machine
sudo sh -c 'echo "deb http://apt.postgresql.org/pub/repos/apt $(lsb_release -cs)-pgdg main" > /etc/apt/sources.list.d/pgdg.list'
wget --quiet -O - https://www.postgresql.org/media/keys/ACCC4CF8.asc | sudo apt-key add -
sudo apt -y update
```

Install PostgreSQL.
```bash
# Install PostgreSQL 14
sudo apt -y install postgresql-14
sudo service postgresql start
```

Create the "denaro" database:
```bash
# Create the denaro database
psql -U postgres
> createdb denaro
> exit
```

Clone the node from GitHub and install all the requirements:
```
# Install the node
git clone https://github.com/denaro-coin/denaro
cd denaro
psql -d denaro -f schema.sql
pip3 install -r requirements.txt
```

Finally run the node.
```bash
# Run the node
uvicorn denaro.node.main:app --port 3006

```

You have to set environmental variables for database access:
- `DENARO_DATABASE_USER`, `postgres`.  
- `DENARO_DATABASE_PASSWORD`, empty.  
- `DENARO_DATABASE_NAME`, `denaro`.  
- `DENARO_DATABASE_HOST`, your database host.  
