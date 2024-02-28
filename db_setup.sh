#!/bin/bash

# Overview:
# Author: The-Sycorax (https://github.com/The-Sycorax)
# This bash script automates the PostgreSQL setup required to run a Denaro node. It also installs other pre-requisites which are used by python modules.
# This script has been specifically designed for Debian/Ubuntu Linux distributions.

# Variables
DB_NAME="denaro"
DB_USER="denaro"
DB_PASS=""

# Install required packages
sudo apt update
sudo apt install postgresql libgmp-dev libpq-dev || { echo "Installation failed"; exit 1; }

# Create database and user
sudo -u postgres psql -c "CREATE DATABASE $DB_NAME;" || { echo "Database creation failed"; exit 1; }
sudo -u postgres psql -c "CREATE USER $DB_USER;" || { echo "User creation failed"; exit 1; }
sudo -u postgres psql -c "ALTER USER $DB_USER WITH PASSWORD '$DB_PASS';" || { echo "Setting password failed"; exit 1; }
sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE $DB_NAME TO $DB_USER;" || { echo "Granting privileges failed"; exit 1; }
sudo -u postgres psql -c "ALTER DATABASE $DB_NAME OWNER TO $DB_USER;" || { echo "Changing database owner failed"; exit 1; }

PG_VERSION=$(pg_config --version | awk '{print $2}' | cut -d '.' -f1)
PG_HBA_CONF="/etc/postgresql/$PG_VERSION/main/pg_hba.conf"

# Modify pg_hba.conf
sudo sed -i.bak '/# "local" is for Unix domain socket connections only/{n;s/peer/trust/;}' $PG_HBA_CONF || { echo "Modification of $PG_HBA_CONF failed"; exit 1; }

# Restart PostgreSQL service
sudo service postgresql restart || { echo "PostgreSQL restart failed"; exit 1; }

# Import schema
psql -U $DB_USER -d $DB_NAME -f schema.sql || { echo "Schema import failed"; exit 1; }

echo "Script executed successfully."