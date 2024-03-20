#!/bin/bash

# Author: The-Sycorax (https://github.com/The-Sycorax)
# License: MIT
# Copyright (c) 2024
#
# Overview:
# This bash script automates the setup required to run a Denaro node. It handles system
# package updates, configures environment variables, configures the PostgreSQL database, 
# sets up a Python virtual environment, installs the required Python dependencies, and 
# initiates the Denaro node. This script ensures that all prerequisites for operating a
# Denaro node are met and properly configured accoring to the user's preference.

# Parse command-line arguments for skipping prompts and setting up DB only
SKIP_APT_INSTALL=false
SKIP_PROMPTS=false
SETUP_DB_ONLY=false

while [[ "$#" -gt 0 ]]; do
    case $1 in
        --skip-prompts) SKIP_PROMPTS=true ;;
        --setup-db) SETUP_DB_ONLY=true ;;
        --skip-package-install) SKIP_APT_INSTALL=true ;;
        *) echo "Unknown parameter passed: $1"; exit 1 ;;
    esac
    shift
done

echo "Starting Denaro node setup..."
echo ""

# Global variables DB and host config
DENARO_DATABASE_USER="denaro"
DENARO_DATABASE_PASSWORD="denaro"
DENARO_DATABASE_NAME="denaro"
DENARO_DATABASE_HOST="127.0.0.1"
DENARO_NODE_HOST="127.0.0.1"
DENARO_NODE_PORT="3006"
USE_DEFAULT_ENV_VARS=false 
# Path to the .env file
env_file=".env"

db_user_changed=false
db_pass_changed=false
db_name_changed=false

# Virtual environment directory
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
        local packages=("gcc" "postgresql" "libgmp-dev" "libpq-dev")
    else
        local packages=("gcc" "postgresql" "libgmp-dev" "libpq-dev" "python3" "python3-dev" "python3-venv")
    fi

    # Check each package and add to the list if it is not installed
    for package in "${packages[@]}"; do
        if ! dpkg-query -W -f='${Status}' $package 2>/dev/null | grep -q "install ok installed"; then
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

# Custom function to read password with asterisk feedback
read_password_with_asterisks() {
    local prompt=$1
    local var_name=$2
    
    if ! $SKIP_PROMPTS && ! $USE_DEFAULT_ENV_VARS; then
        echo -n "$prompt "
        local password=""
        local char_count=0

        # Disable echo
        stty -echo

        while IFS= read -r -s -n1 char; do
            # Enter - accept password
            if [[ $char == $'\0' ]]; then
                break
            fi
            # Backspace
            if [[ $char == $'\177' ]]; then
                if [ $char_count -gt 0 ]; then
                    char_count=$((char_count-1))
                    password="${password%?}"
                    echo -en "\b \b"
                fi
                continue
            fi
            echo -n '*'
            char_count=$((char_count+1))
            password+="$char"
        done

        # Re-enable echo
        stty echo
        echo

        # Update global variable
        eval $var_name="'$password'"
    fi
}

# Function to validate the port number input
validate_port_input() {
    local prompt="$1"
    local var_name="$2"
    local input_port=""
    local show_current_vars="$3"

    if $show_current_vars;then
        local var_value=$(grep "^$var_name=" "$env_file" | cut -d'=' -f2-)
    else
        local var_value="${!var_name}"
    fi

    while true; do
        read -p "$prompt " input_port
        if [[ -z "$input_port" ]]; then
            if $show_current_vars;then
                input_port=$var_value
            else
                input_port="3006"
            fi
            break
        elif ! [[ "$input_port" =~ ^[0-9]+$ ]]; then
            echo "Invalid input. Port must be a number."
            echo ""
        elif (( input_port < 1024 || input_port > 49151 )); then
            echo "Invalid port number. Port must be between 1024 and 49151."
            echo ""
        else
            break
        fi
    done
    eval $var_name="'$input_port'"
}

# Function to load existing .env variables into global variables
load_env_variables() {
    if [[ -f "$env_file" ]]; then
        #echo "Loading existing configurations..."
        while IFS='=' read -r key value; do
            if [[ $key == DENARO_DATABASE_USER || $key == DENARO_DATABASE_PASSWORD || $key == DENARO_DATABASE_NAME || $key == DENARO_DATABASE_HOST || $key == DENARO_NODE_HOST || $key == DENARO_NODE_PORT ]]; then
                eval $key="'$value'"
            fi
        done < "$env_file"
    fi
}

# Function to read a variable from the .env file
read_env_variable() {
    local var_name="$1"
    echo $(grep -E "^${var_name}=" .env | cut -d '=' -f2-)
}

# Function to identify missing or incomplete configuration variables
identify_missing_variables() {
    local env_file="$1"
    local missing_vars=()

    # Check each variable to see if it's present and has a value
    grep -qE "^DENARO_DATABASE_USER=.+" "$env_file" || missing_vars+=("DENARO_DATABASE_USER")
    grep -qE "^DENARO_DATABASE_PASSWORD=.+" "$env_file" || missing_vars+=("DENARO_DATABASE_PASSWORD")
    grep -qE "^DENARO_DATABASE_NAME=.+" "$env_file" || missing_vars+=("DENARO_DATABASE_NAME")
    grep -qE "^DENARO_DATABASE_HOST=.+" "$env_file" || missing_vars+=("DENARO_DATABASE_HOST")
    grep -qE "^DENARO_NODE_HOST=.+" "$env_file" || missing_vars+=("DENARO_NODE_HOST")
    grep -qE "^DENARO_NODE_PORT=.+" "$env_file" || missing_vars+=("DENARO_NODE_PORT")

    echo "${missing_vars[@]}"
}

# Function to update or append a variable in the .env file
update_variable() {
    local prompt="$1"
    local var_name="$2"
    local update_missing_vars="$3"
    local show_current_vars="$4"
    local env_file=".env"  # Path to the .env file
    
    # Define default values explicitly for each variable
    local default_value="${!var_name}"
    
    # Extract the current value directly from the .env file
    local current_value=$(grep "^$var_name=" "$env_file" | cut -d'=' -f2-)
    
    if $show_current_vars;then
        local var_value=$(grep "^$var_name=" "$env_file" | cut -d'=' -f2-)
        local prompt_value_string="current:"
    else
        local var_value="${!var_name}"
        local prompt_value_string="default:"
    fi

    if ! $SKIP_PROMPTS && ! $USE_DEFAULT_ENV_VARS; then
        if [[ "$var_name" == "DENARO_DATABASE_PASSWORD" ]]; then
            while true; do
                # Special handling for password input with asterisks feedback
                read_password_with_asterisks "$prompt:" "$var_name"
                local password_value_1=$(echo $DENARO_DATABASE_PASSWORD | sha256sum | cut -d' ' -f1)
                if [[ -z $DENARO_DATABASE_PASSWORD ]]; then
                    echo "Password can not be empty, please try again."
                    echo ""
                else
                    read_password_with_asterisks "Confirm database password:" "$var_name" $show_current_vars
                    local password_value_2=$(echo $DENARO_DATABASE_PASSWORD | sha256sum | cut -d' ' -f1)
                    if [[ "$password_value_1" != "$password_value_2" ]]; then
                        echo "Passwords do not match, please try again."
                        echo ""
                    else
                        break
                    fi
                fi
            done
            
        elif [[ "$var_name" == "DENARO_NODE_PORT" ]]; then
            # Special handling for port input with validation
            validate_port_input "$prompt ($prompt_value_string $var_value):" "$var_name" $show_current_vars

        else
            # Prompt for other inputs with showing the default value
            read -p "$prompt ($prompt_value_string $var_value): " value
            if [[ -z "$value" ]]; then
                if $show_current_vars;then
                    value="$var_value"
                else
                    # Use default value if no input is provided
                    value="$default_value"  
                fi
            fi
            eval $var_name="'$value'"
        fi

    elif [[ -z "$current_value" ]]; then
        if $show_current_vars;then
            eval $var_name="'$var_value'"
        else
            # If there's no current value, use the default
            eval $var_name="'$default_value'"
        fi
    fi

    # Check if the variable already exists in the .env file
    if grep -q "^$var_name=" "$env_file"; then
        # Variable exists, update its value using sed
        sed -i "s/^$var_name=.*/$var_name='${!var_name}'/" "$env_file"
    else
        # Variable does not exist, append it
        echo "$var_name='${!var_name}'" >> "$env_file"
    fi
}

# Main function to set variables in a .env file with user-specified variables or defaults
set_env_variables() {
    echo ""
    echo "Starting dotenv configuration..."
    echo ""
    local env_file=".env"
    local PROMPT_FOR_DEFAUT=true
    local update_missing_vars=false
    local show_current_vars=false

    # Check if the .env file already exists
    if [[ -f "$env_file" ]]; then
        echo "$env_file file already exists."
        echo ""
        
        local missing_vars=($(identify_missing_variables "$env_file"))
        if [ ${#missing_vars[@]} -eq 0 ]; then
            
            if ! $SKIP_PROMPTS; then
                # Prompt the user to decide if they want to update the current configuration
                while true; do
                    read -p "Do you want to update the current configuration? (Y/N): " update_choice
                    case "$update_choice" in
                        [Yy] )
                            local update_missing_vars=true
                            local show_current_vars=true
                            PROMPT_FOR_DEFAUT=false
                            missing_vars=("DENARO_DATABASE_USER" "DENARO_DATABASE_PASSWORD" "DENARO_DATABASE_NAME" "DENARO_DATABASE_HOST" "DENARO_NODE_HOST" "DENARO_NODE_PORT")
                            echo "Leave blank to keep the current value."
                            echo ""
                            break;;
                        [Nn] )
                            echo "Keeping current configuration."
                            load_env_variables
                            return 0;;
                        * )
                            echo "Invalid input. Please enter 'Y' or 'N'."; echo "";;
                    esac
                done
            else
                echo "Keeping current configuration."
                load_env_variables
                return 0
            fi
        else
            echo "The .env file is incomplete or has empty values."
            echo "Missing variables: ${missing_vars[*]}"
            echo ""
            local update_missing_vars=true
            PROMPT_FOR_DEFAULT=true
        fi
    else
        echo "$env_file file does not exist."
        echo "Proceeding with configuration..."
        echo ""
        PROMPT_FOR_DEFAULT=true
        > "$env_file"  # Clear or create .env file with the new configuration
        local missing_vars=($(identify_missing_variables "$env_file"))
    fi

    if ! $SKIP_PROMPTS; then
        if $PROMPT_FOR_DEFAUT; then
            while true; do
                read -p "Do you want to use the default values for configuration? (Y/N): " use_defaults
                case "$use_defaults" in
                    [Yy] ) 
                        USE_DEFAULT_ENV_VARS=true 
                        echo "Using default values for configuration."
                        break;;
                    [Nn] )
                        USE_DEFAULT_ENV_VARS=false
                        echo "Leave blank to use the default value."
                        echo ""
                        break;;
                    * ) 
                        echo "Invalid input. Please enter 'Y' or 'N'."; echo "";;
                esac
            done
        else
            USE_DEFAULT_ENV_VARS=false
        fi
    else
        USE_DEFAULT_ENV_VARS=true
        echo "Using default values for configuration."
    fi
    
    local initial_db_user=$(read_env_variable "DENARO_DATABASE_USER" | sha256sum | cut -d' ' -f1)
    local initial_db_pass=$(read_env_variable "DENARO_DATABASE_PASSWORD" | sha256sum | cut -d' ' -f1)
    local initial_db_name=$(read_env_variable "DENARO_DATABASE_NAME" | sha256sum | cut -d' ' -f1)
   
    # Use the update_variable function for each required variable based on its presence in missing_vars array
    [[ " ${missing_vars[*]} " =~ " DENARO_DATABASE_USER " ]] && update_variable "Enter database username" "DENARO_DATABASE_USER" $update_missing_vars $show_current_vars
    [[ " ${missing_vars[*]} " =~ " DENARO_DATABASE_PASSWORD " ]] && update_variable "Enter password for database user" "DENARO_DATABASE_PASSWORD" $update_missing_vars $show_current_vars
    [[ " ${missing_vars[*]} " =~ " DENARO_DATABASE_NAME " ]] && update_variable "Enter database name" "DENARO_DATABASE_NAME" $update_missing_vars $show_current_vars
    [[ " ${missing_vars[*]} " =~ " DENARO_DATABASE_HOST " ]] && update_variable "Enter database host" "DENARO_DATABASE_HOST" $update_missing_vars $show_current_vars
    [[ " ${missing_vars[*]} " =~ " DENARO_NODE_HOST " ]] && update_variable "Enter local Denaro node address or hostname" "DENARO_NODE_HOST" $update_missing_vars $show_current_vars
    [[ " ${missing_vars[*]} " =~ " DENARO_NODE_PORT " ]] && update_variable "Enter local Denaro node port" "DENARO_NODE_PORT" $update_missing_vars $show_current_vars
    
    local new_db_user=$(read_env_variable "DENARO_DATABASE_USER" | sha256sum | cut -d' ' -f1)
    local new_db_pass=$(read_env_variable "DENARO_DATABASE_PASSWORD" | sha256sum | cut -d' ' -f1)
    local new_db_name=$(read_env_variable "DENARO_DATABASE_NAME" | sha256sum | cut -d' ' -f1)
    
    [[ "$initial_db_user" != "$new_db_user" ]] && db_user_changed=true
    [[ "$initial_db_pass" != "$new_db_pass" ]] && db_pass_changed=true
    [[ "$initial_db_name" != "$new_db_name" ]] && db_name_changed=true
    
    echo ""
    echo "$env_file file configured."
}

# Save the current directory
original_dir=$(pwd)

setup_database() {
    local db_modified=false

    # Change to /tmp before running commands that may cause permission denied notices
    cd /tmp
    echo ""
    echo "Starting Database Setup..."
    echo ""
    echo "Checking if '$DENARO_DATABASE_NAME' database exists..."
    # Check if database exists
    if ! sudo -u postgres psql -lqt | cut -d \| -f 1 | grep -qw $DENARO_DATABASE_NAME; then
        echo "Creating '$DENARO_DATABASE_NAME' database..."
        sudo -u postgres psql -c "CREATE DATABASE $DENARO_DATABASE_NAME;" >&/dev/null || { echo "Database creation failed"; exit 1; }
        db_modified=true
    else
        echo "'$DENARO_DATABASE_NAME' database already exists, skipping..."
    fi
    echo ""
    
    echo "Checking if the database user exists..."
    # Check if user exists
    if ! sudo -u postgres psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='$DENARO_DATABASE_USER'" | grep -q 1; then
        echo "Creating user $DENARO_DATABASE_USER..."
        sudo -u postgres psql -c "CREATE USER $DENARO_DATABASE_USER;" >&/dev/null || { echo "User creation failed"; exit 1; }
        db_modified=true
    else
        echo "Database user '$DENARO_DATABASE_USER' already exists, skipping..."
    fi
    echo ""
    
    echo "Checking if password is set for database user..."
    has_password=$(sudo -u postgres psql -X -A -t -c "SELECT rolpassword IS NULL FROM pg_authid WHERE rolname = '$DENARO_DATABASE_USER';")
    if [ ! "$has_password" = "f" ]; then
        echo "Setting password for database user..."
        sudo -u postgres psql -c "ALTER USER $DENARO_DATABASE_USER WITH PASSWORD '$DENARO_DATABASE_PASSWORD';" >&/dev/null || { echo "Setting password failed"; exit 1; }
        db_modified=true
        echo "Password set."
    else
        if $db_pass_changed; then
            sudo -u postgres psql -c "ALTER USER $DENARO_DATABASE_USER WITH PASSWORD '$DENARO_DATABASE_PASSWORD';" >&/dev/null || { echo "Setting password failed"; exit 1; }
            echo "Password set."
        else
            echo "Password already set for database user, skipping..."
        fi
    fi
    echo ""
    
    # Check if user already has all privileges on the database
    echo "Checking if user has all database privileges..."
    has_CTc_priv=$(sudo -u postgres psql -X -A -t -c "SELECT bool_or(datacl::text LIKE '%$DENARO_DATABASE_USER=CTc%') FROM pg_database WHERE datname = '$DENARO_DATABASE_NAME';")
    if [ ! "$has_CTc_priv" = "t" ]; then
        echo "Granting all database privileges to user..."
        sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE $DENARO_DATABASE_NAME TO $DENARO_DATABASE_USER;" >&/dev/null || { echo "Granting privileges failed"; exit 1; }
        sudo -u postgres psql -d $DENARO_DATABASE_NAME -c "GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO $DENARO_DATABASE_USER;" >&/dev/null || { echo "Granting privileges failed"; exit 1; }
        sudo -u postgres psql -d $DENARO_DATABASE_NAME -c "GRANT ALL ON SCHEMA public TO $DENARO_DATABASE_USER;" >&/dev/null || { echo "Granting privileges failed"; exit 1; }
        db_modified=true
        echo "Privileges granted."
    else
        echo "User already granted database privileges, skipping..."
    fi
    echo ""
    
    # Check if the database owner is already set to the specified user
    echo "Checking if database owner is already '$DENARO_DATABASE_USER'..."
    CURRENT_OWNER=$(sudo -u postgres psql -tAc "SELECT d.datname, pg_catalog.pg_get_userbyid(d.datdba) as owner FROM pg_catalog.pg_database d WHERE d.datname = '$DENARO_DATABASE_NAME'")
    if [[ $CURRENT_OWNER != *"$DENARO_DATABASE_USER"* ]]; then
        echo "Setting database owner to '$DENARO_DATABASE_USER'..."
        sudo -u postgres psql -c "ALTER DATABASE $DENARO_DATABASE_NAME OWNER TO $DENARO_DATABASE_USER;" >&/dev/null || { echo "Setting database owner failed"; exit 1; }
        db_modified=true
        echo "Database owner set."
    else
        echo "Database owner is already '$DENARO_DATABASE_USER'."
    fi
    echo ""
    
    # Change back to the original directory
    cd "$original_dir"
    
    PG_VERSION=$(pg_config --version | awk '{print $2}' | cut -d '.' -f1)
    PG_HBA_CONF="/etc/postgresql/$PG_VERSION/main/pg_hba.conf"
    
    echo "Checking if pg_hba.conf needs modification..."
    # Check if modification is needed in pg_hba.conf
    if ! sudo grep -q 'local   all             all                                     md5' $PG_HBA_CONF; then
        echo "Modifying $PG_HBA_CONF for trust authentication..."
        sudo sed -i.bak '/# "local" is for Unix domain socket connections only/{n;s/peer/md5/;}' $PG_HBA_CONF || { echo "Modification of $PG_HBA_CONF failed"; exit 1; }
        db_modified=true
    else
        echo "pg_hba.conf already set for md5 authentication, skipping..."
    fi
    echo ""

    if $db_modified; then
        echo "Restarting PostgreSQL service..."
        # Restart PostgreSQL service
        sudo service postgresql restart || { echo "PostgreSQL restart failed"; exit 1; }
        echo ""
    
        echo "Importing database schema from schema.sql..."
        # Import schema
        PGPASSWORD=$DENARO_DATABASE_PASSWORD psql -U $DENARO_DATABASE_USER -d $DENARO_DATABASE_NAME -c "SET client_min_messages TO WARNING;" -f schema.sql >&/dev/null || { echo "Schema import failed"; exit 1; }
        echo ""
        echo "Database setup complete!"
        echo ""
    else
        echo "No modifications to database made."
        echo ""
    fi
}

# Only setup the database if --setup-db is specified, then exit
if $SETUP_DB_ONLY; then
    # Only install apt packages if --skip-package-install is specified
    if $SKIP_APT_INSTALL; then
        echo "Skipping APT package installation..."
    else
        update_and_install_packages
    fi
    set_env_variables
    setup_database
    exit 0
fi

# Skip apt package installation if --skip-package-install is specified
if $SKIP_APT_INSTALL; then
    echo "Skipping APT package installation..."
else
    update_and_install_packages
fi

set_env_variables
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

# Function to check if pip requirements are installed and to ask for installation
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

sep = '~'
packages = []
for m in missing:
    package_name = m.split(sep, 1)[0]
    packages.append(package_name)
packages = ', '.join(packages)
print(str(packages))
")

    if [ ${#missing_packages} -eq 0 ]; then
        echo "Required packages are already installed."
        return
    else
        echo -e "\nThe following packages from requirements.txt are missing:\n${missing_packages}."
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
    pip install -r requirements.txt || { echo "Failed to install python packages."; exit 1; }
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
            echo ""
        fi
    done
}

# Validate start_node input
start_node(){
    echo ""
    echo "Starting Denaro node on port $DENARO_NODE_PORT..."
    echo "Press Ctrl+C to exit."
    echo ""
    uvicorn denaro.node.main:app --port $DENARO_NODE_PORT || { echo "Failed to start Denaro Node"; exit 1; }
}

if $SKIP_PROMPTS; then
    start_node
else
    validate_start_node_response
    if [[ "$start_node" =~ ^[Yy]$ ]]; then
        start_node
    else
        echo "Skipped..."
    fi
fi

echo ""
echo "Script executed successfully."