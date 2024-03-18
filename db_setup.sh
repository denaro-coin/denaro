#!/bin/bash

# Author: The-Sycorax (https://github.com/The-Sycorax)
# License: MIT
# Copyright (c) 2024
#
# Overview:
# This bash script automates the PostgreSQL setup required to run a Denaro node. It also installs other pre-requisites which are used by python modules.
# This script has been specifically designed for Debian/Ubuntu Linux distributions.

echo "Starting Denaro node setup..."

# Variables
DB_NAME="denaro"
DB_USER="denaro"
DB_PASS=""

echo "Updating package lists..."
# Install required packages
sudo apt update
echo "Installing required packages..."
sudo apt install postgresql libgmp-dev libpq-dev || { echo "" && echo "Installation failed"; exit 1; }
echo "Package installation completed."
echo ""

# Save the current directory
original_dir=$(pwd)

# Change to /tmp before running commands that may cause permission denied notices
cd /tmp

echo "Checking if '$DB_NAME' database exists..."
# Check if database exists
if ! sudo -u postgres psql -lqt | cut -d \| -f 1 | grep -qw $DB_NAME; then
    echo "Creating '$DB_NAME' database..."
    sudo -u postgres psql -c "CREATE DATABASE $DB_NAME;" || { echo "Database creation failed"; exit 1; }
else
    echo "'$DB_NAME' database already exists, skipping..."
fi
echo ""

echo "Checking if the database user exists..."
# Check if user exists
if ! sudo -u postgres psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='$DB_USER'" | grep -q 1; then
    echo "Creating user $DB_USER..."
    sudo -u postgres psql -c "CREATE USER $DB_USER;" || { echo "User creation failed"; exit 1; }
else
    echo "User '$DB_USER' already exists, skipping..."
fi
echo ""

echo "Setting password for database user..."
sudo -u postgres psql -c "ALTER USER $DB_USER WITH PASSWORD '$DB_PASS';" || { echo "Setting password failed"; exit 1; }
echo "Password set."
echo ""

echo "Granting all database privileges to user..."
sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE $DB_NAME TO $DB_USER;" || { echo "Granting privileges failed"; exit 1; }
echo ""

echo "Changing database owner to '$DB_USER'..."
sudo -u postgres psql -c "ALTER DATABASE $DB_NAME OWNER TO $DB_USER;" || { echo "Changing database owner failed"; exit 1; }
echo ""

# Change back to the original directory
cd "$original_dir"

PG_VERSION=$(pg_config --version | awk '{print $2}' | cut -d '.' -f1)
PG_HBA_CONF="/etc/postgresql/$PG_VERSION/main/pg_hba.conf"

echo "Checking if pg_hba.conf needs modification..."
# Check if modification is needed in pg_hba.conf
if ! sudo grep -q 'local   all             all                                     trust' $PG_HBA_CONF; then
    echo "Modifying $PG_HBA_CONF for trust authentication..."
    sudo sed -i.bak '/# "local" is for Unix domain socket connections only/{n;s/peer/trust/;}' $PG_HBA_CONF || { echo "Modification of $PG_HBA_CONF failed"; exit 1; }
else
    echo "pg_hba.conf already set for trust authentication, skipping..."
fi
echo ""

echo "Restarting PostgreSQL service..."
# Restart PostgreSQL service
sudo service postgresql restart || { echo "PostgreSQL restart failed"; exit 1; }
echo ""

echo "Importing database schema from schema.sql..."
# Import schema (consider making this idempotent as well, depending on your schema)
psql -U $DB_USER -d $DB_NAME -c "SET client_min_messages TO WARNING;" -f schema.sql || { echo "Schema import failed"; exit 1; }
echo ""

echo "Script executed successfully."