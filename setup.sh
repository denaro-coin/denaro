#!/bin/bash

# Overview:
# Author: The-Sycorax (https://github.com/The-Sycorax)
# This bash script automates the PostgreSQL setup required to run a Denaro node. It also installs other pre-requisites which are used by python modules.
# This script has been specifically designed for Debian/Ubuntu Linux distributions.

# Parse command-line arguments for skipping prompts and setting up DB only
SKIP_PROMPTS=false
SETUP_DB_ONLY=false

while [[ "$#" -gt 0 ]]; do
    case $1 in
        --skip-prompts) SKIP_PROMPTS=true ;;
        --setup-db) SETUP_DB_ONLY=true ;;
        *) echo "Unknown parameter passed: $1"; exit 1 ;;
    esac
    shift
done

echo "Starting Denaro node setup..."
echo ""

# Variables
DB_NAME="denaro"
DB_USER="denaro"
DB_PASS=""
VENV_DIR="venv"

update_and_install_packages() {
    echo "Updating package lists..."
    sudo apt update
    echo ""

    echo "Checking required system packages..."

    # Initialize an array to hold the names of packages that need to be installed
    local packages_to_install=()

    # List of all packages to check
    if $SETUP_DB_ONLY; then
        local packages=("postgresql" "libgmp-dev" "libpq-dev")
    else
        local packages=("postgresql" "libgmp-dev" "libpq-dev" "python3-venv")
    fi

    # Check each package and add to the list if it is not installed
    for package in "${packages[@]}"; do
        if ! dpkg -l | grep -qw $package; then
            echo "Package $package is not installed."
            packages_to_install+=($package)
        else
            echo "Package $package is already installed."
        fi
    done

    # Check if there are any packages to install
    if [ ${#packages_to_install[@]} -gt 0 ]; then
        if $SKIP_PROMPTS; then
            echo "Installing required packages: ${packages_to_install[*]}"
            echo ""
            sudo apt install -y ${packages_to_install[@]} || { echo ""; echo "Installation failed"; exit 1; }
        else
            echo ""
            sudo apt install ${packages_to_install[@]} || { echo ""; echo "Installation failed"; exit 1; }
        fi
        echo ""
        echo "Package installation complete."
    fi
}

# Save the current directory
original_dir=$(pwd)

setup_database() {
    # Change to /tmp before running commands that may cause permission denied notices
    cd /tmp
    echo ""
    echo "Starting Database Setup..."
    echo ""
    echo "Checking if '$DB_NAME' database exists..."
    # Check if database exists
    if ! sudo -u postgres psql -lqt | cut -d \| -f 1 | grep -qw $DB_NAME; then
        echo "Creating '$DB_NAME' database..."
        sudo -u postgres psql -c "CREATE DATABASE $DB_NAME;" >&/dev/null || { echo "Database creation failed"; exit 1; }
    else
        echo "'$DB_NAME' database already exists, skipping..."
    fi
    echo ""
    
    echo "Checking if the database user exists..."
    # Check if user exists
    if ! sudo -u postgres psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='$DB_USER'" | grep -q 1; then
        echo "Creating user $DB_USER..."
        sudo -u postgres psql -c "CREATE USER $DB_USER;" >&/dev/null || { echo "User creation failed"; exit 1; }
    else
        echo "Database user '$DB_USER' already exists, skipping..."
    fi
    echo ""
    
    echo "Setting password for database user..."
    sudo -u postgres psql -c "ALTER USER $DB_USER WITH PASSWORD '$DB_PASS';" >&/dev/null || { echo "Setting password failed"; exit 1; }
    echo "Password set."
    echo ""
    
    # Check if user already has all privileges on the database
    echo "Granting all database privileges to user..."
    sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE $DB_NAME TO $DB_USER;" >&/dev/null || { echo "Granting privileges failed"; exit 1; }
    echo "Privileges granted."
    echo ""
    
    # Check if the database owner is already set to the specified user
    echo "Checking if database owner is already '$DB_USER'..."
    CURRENT_OWNER=$(sudo -u postgres psql -tAc "SELECT d.datname, pg_catalog.pg_get_userbyid(d.datdba) as owner FROM pg_catalog.pg_database d WHERE d.datname = '$DB_NAME'")
    if [[ $CURRENT_OWNER != *"$DB_USER"* ]]; then
        echo "Changing database owner to '$DB_USER'..."
        sudo -u postgres psql -c "ALTER DATABASE $DB_NAME OWNER TO $DB_USER;" >&/dev/null || { echo "Changing database owner failed"; exit 1; }
        echo "Database owner changed."
    else
        echo "Database owner is already '$DB_USER'."
    fi
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
    psql -U $DB_USER -d $DB_NAME -c "SET client_min_messages TO WARNING;" -f schema.sql >&/dev/null || { echo "Schema import failed"; exit 1; }
    echo ""
    echo "Datebase setup complete!"
    echo ""
}

# Only setup the database if --setup-db is specified, then exit
if $SETUP_DB_ONLY; then
    update_and_install_packages
    setup_database
    exit 0
fi

update_and_install_packages
setup_database

VENV_DIR="venv"
echo "Checking if Python virtual environment exists..."

# Function to ask for virtual environment setup
setup_venv() {
    if [ ! -d "$VENV_DIR" ]; then
        echo "A virtual environment does not exist."
        echo ""
        if $SKIP_PROMPTS; then
            echo "Creating virtual environment in ./$VENV_DIR..."
            python3 -m venv $VENV_DIR
            source $VENV_DIR/bin/activate
            echo "Virtual environment created and activated."
        else            
            echo "Creating a Python virtual environment is highly recommended to avoid dependency conflicts with system-wide Python packages."
            echo "It provides an isolated space for project dependencies."
            #echo ""
            while true; do
                read -p "Do you want to create a Python virtual environment? (Y/N): " create_venv
                case "$create_venv" in
                    [Yy] )
                        echo ""
                        echo "Creating virtual environment in ./$VENV_DIR..."
                        python3 -m venv $VENV_DIR
                        source $VENV_DIR/bin/activate
                        echo "Virtual environment created and activated."
                        break;;
                    [Nn] )
                        echo ""
                        echo "Skipped..."
                        break;;
                    * )
                        echo "Invalid input. Please enter 'Y' or 'N'."
                        echo ""
                esac
            done
        fi
    else
        activate_venv
    fi
}

# Function to ask for virtual environment activation
activate_venv() {
    if [[ -z "$VIRTUAL_ENV" ]]; then
        echo "Virtual environment already exists but is not active."
        if $SKIP_PROMPTS; then
            echo ""
            echo "Activating virtual environment..."
            source $VENV_DIR/bin/activate
        else            
            while true; do
                read -p "Do you want to activate it? (Y/N): " activate_venv
                case "$activate_venv" in
                    [Yy] )
                        source $VENV_DIR/bin/activate
                        echo ""
                        echo "Virtual environment activated."
                        break;;
                    [Nn] )
                        echo ""
                        echo "Skipped..."
                        break;;
                    * )
                        echo "Invalid input. Please enter 'Y' or 'N'."
                        echo ""
                esac
            done
        fi
    else
        echo "Virtual environment already exists and is active."
    fi
}

# Function to check if pip requirements are installed and ask for installation
pip_install() {
    echo ""
    echo "Checking required Python packages..."
    # Check for missing packages using a Python script
    readarray -t missing_packages < <(python3 -c "
import pkg_resources
from pkg_resources import DistributionNotFound, VersionConflict

requirements = [str(r) for r in pkg_resources.parse_requirements(open('requirements.txt'))]

missing = []
for req in requirements:
    try:
        pkg_resources.require(req)
    except (DistributionNotFound, VersionConflict):
        missing.append(req)

for m in missing:
    print(m)
")

    if [ ${#missing_packages[@]} -eq 0 ]; then
        echo "Required packages are already installed."
        return
    else
        echo -e "The following packages from requirements.txt are missing:\n${missing_packages[*]}"
    fi

    # Skip the first prompt if SKIP_PROMPTS is true
    if ! $SKIP_PROMPTS; then
        while true; do
            read -p "Do you want to install the missing Python packages? (Y/N): " install_req
            case "$install_req" in
                [Yy] ) break;;
                [Nn] ) echo ""; echo "Cancelled..."; exit 1;;
                * ) echo "Invalid input. Please enter 'Y' or 'N'."; echo ""; continue;;
            esac
        done
    fi

    # Check environment and potentially warn about global installation
    if [[ -z "$VIRTUAL_ENV" ]]; then
        echo ""
        echo "Warning: You are not currently in a virtual environment!"
        echo "Installing globally can affect system-wide Python packages and cause dependency conflicts."
        while true; do
            read -p "Are you sure you want to continue? (Y/N): " confirm_global_install
            case "$confirm_global_install" in
                [Yy] ) break;;
                [Nn] ) echo ""; echo "Cancelled..."; exit 1;;
                * ) echo "Invalid input. Please enter 'Y' or 'N'."; echo ""; continue;;
            esac
        done
    fi
    echo ""
    echo "Installing required Python packages..."
    echo ""
    # Proceed with installation
    pip install -r requirements.txt
    echo ""
    if [[ -z "$VIRTUAL_ENV" ]]; then
        echo "Python packages installed globally."
    else
        echo "Python packages installed within virtual environment."
    fi
}

# Setup or activate virtual environment
setup_venv

# Ask user if they want to install pip requirements
pip_install

echo ""
# Ask user if they want to start the node
echo "Node setup complete!"
echo ""
echo "Ready to start the Denaro node."

# Function to validate the initial response (y/n)
validate_start_node_response() {
    while true; do
        # Prompt the user for input
        read -p "Do you want to start the Denaro node now? (Y/N): " start_node
        # Check if the response is either 'y' or 'n' (case-insensitive)
        if [[ "$start_node" =~ ^[YyNn]$ ]]; then
            break  # Exit the loop if the input is valid
        else
            echo "Invalid input. Please enter 'Y' or 'N'."  # Prompt for valid input
        fi
    done
}

# Function to validate the port number input
validate_port_input() {
    echo ""
    while true; do
        # Prompt the user for the port number with a default value
        read -p "Enter the port number you want to use (default 3006): " port
        # Use default port 3006 if no input is provided
        if [[ -z "$port" ]]; then
            port=3006
            break  # Exit the loop if default is used
        elif [[ "$port" =~ ^[0-9]+$ ]] && [ "$port" -ge 1024 ] && [ "$port" -le 49151 ]; then
            break  # Exit the loop if the port is a valid number within range
        else
            echo "Invalid port number. Please enter a number between 1024 and 49151."  # Prompt for valid input
        fi
    done
}

# Validate start_node input
if $SKIP_PROMPTS; then
    echo ""
    echo "Starting Denaro node for localhost on port 3006..."
    echo "Press Ctrl+C to exit."
    echo ""
    uvicorn denaro.node.main:app --port 3006 || { echo "Failed to start Denaro Node"; exit 1; }
else
    validate_start_node_response
    if [[ "$start_node" =~ ^[Yy]$ ]]; then    
        # Validate port number input
        validate_port_input
        echo ""
        echo "Starting Denaro node for localhost on port $port..."
        echo "Press Ctrl+C to exit."
        echo ""
        # Attempt to start the Denaro node on the specified port, exit with error if it fails
        uvicorn denaro.node.main:app --port $port || { echo "Failed to start Denaro Node"; exit 1; }
    else
        echo "Skipped..."
    fi
fi

echo ""
echo "Script executed successfully."