# DevContainer CLI Port Forwarder

# Overview
This Python script dynamically forward ports from a host machine to a Docker container according to `devcontainer.json` **forwardPorts**.

This Python script is created because currently DevContainer CLI does not support port forwarding, see [devcontainers/cli issue](https://github.com/devcontainers/cli/issues/22)

## Usage Context
- This script is only needed if you are managing your containers directly with the **devcontainer CLI**.
- If you are using vSCode with the Visual Studio Code Dev Containers extension,The VS Code extension already includes built-in support for port forwarding you do not need to use this script.

## Prerequisites
Python 3 interpreter installed on the host machine.

## Features
- Dynamic Port Forwarding: Automates the process of forwarding specified ports from the host to a Docker container.
- Automatic Shutdown: The script automatically exits when the associated Docker container stops running.

# Usage
git clone this project under your project's `.devcontainer` directory, or anywhere you like.

In your **devcontainer.json**, set the `initializeCommand` to run the script in the background when the container is being initialized:

```json
"initializeCommand": "python3 .devcontainer/devcontainer-cli-port-forwarder/forwarder.py &"
```

To enable verbose output, which provides more detailed information about the port forwarding process, modify the initializeCommand as follows:
```json
"initializeCommand": "python3 .devcontainer/devcontainer-cli-port-forwarder/forwarder.py verbose &"
```

Once configured in your devcontainer.json, the script will automatically start when you create a devcontainer using the devcontainer CLI. It listens on specified ports and forwards them to the Docker container.

- The script runs in the background and does not require manual intervention once started.
- When the Docker container stops, the script detects this and exits automatically, ensuring that resources are not left unnecessarily consumed on the host machine.
