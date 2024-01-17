import pprint
import asyncio
import json
import os
import subprocess
import time
import sys

VERBOSE = False

# Maxinum time to wait for the container to start
MAX_WAIT_TIME = int(os.getenv("PORT_FORWARDER_MAX_WAIT_TIME", 60))

# Flag to indicate if the server should stop running
STOP_RUNNING = False


def verbose_print(message, display=False):
    if VERBOSE or display:
        print(f"[*] forwarder -- {message}")


async def is_container_running(container_id):
    cmd = ["docker", "inspect", "-f", "{{.State.Running}}", container_id]
    process = await asyncio.create_subprocess_exec(*cmd, stdout=subprocess.PIPE)
    stdout, _ = await process.communicate()
    return stdout.decode().strip() == "true"


async def monitor_container(container_id):
    global STOP_RUNNING
    while True:
        container_running = await is_container_running(container_id)
        if not container_running:
            STOP_RUNNING = True
            break
        await asyncio.sleep(1)  # Check every second


async def forward_data(source, target):
    while True:
        data = await source.read(4096)
        if not data:
            break
        target.write(data)
        await target.drain()


async def handle_client(reader, writer, args):
    # Setting up the subprocess to run the command
    (container_id, container_ip, remote_user, port) = args

    start_time = time.time()
    while not await is_container_running(container_id):
        await asyncio.sleep(1)  # Wait and check again in 1 second
        if time.time() - start_time > MAX_WAIT_TIME:
            verbose_print(
                f"Timeout: Container {container_id} did not start within {MAX_WAIT_TIME} seconds."
            )
            writer.close()
            await writer.wait_closed()
            return

    # Now the container is running, proceed with docker exec
    try:
        command = [
            "docker",
            "exec",
            "-i",
            container_id,
            "bash",
            "-c",
            f"su - {remote_user} -c 'socat - TCP:localhost:{port}'",
        ]
        proc = await asyncio.create_subprocess_exec(
            *command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
        )
        verbose_print(f"Execute: {' '.join(command)}")

        # Give a brief moment for the command to start and potentially fail
        await asyncio.sleep(0.5)

        # Check if the subprocess was successfully started
        if proc.returncode is not None:
            # The process terminated immediately, handle the error
            verbose_print(
                f"Error: subprocess terminated immediately with return code {proc.returncode}"
            )
            # Check if stderr is available and read from it
            if proc.stdout is not None:
                if stdout := await proc.stdout.read():
                    verbose_print(f"Error in subprocess: {stdout.decode()}")

            if proc.stderr is not None:
                if stderr := await proc.stdout.read():
                    verbose_print(f"Error in subprocess: {stderr.decode()}")

            writer.close()
            await writer.wait_closed()
            return
    except OSError as e:
        # Handle errors related to subprocess execution
        verbose_print(f"Error executing subprocess: {e}")
        writer.close()
        await writer.wait_closed()
        return

    # Separate tasks for reading and writing in both directions
    client_to_container = asyncio.create_task(forward_data(reader, proc.stdin))
    container_to_client = asyncio.create_task(forward_data(proc.stdout, writer))

    # Wait for both tasks to complete
    await asyncio.wait(
        [client_to_container, container_to_client], return_when=asyncio.FIRST_COMPLETED
    )

    writer.close()
    await writer.wait_closed()
    proc.terminate()
    verbose_print(f"Termiate process in {container_id} '{command[-1]}'")


async def start_server(container_id: str, container_ip: str, remote_user: str, port):
    host = "0.0.0.0"
    server = await asyncio.start_server(
        lambda r, w: handle_client(
            r, w, (container_id, container_ip, remote_user, port)
        ),
        host,
        port,
    )

    async with server:
        await server.start_serving()
        verbose_print(f"Listening on {host}:{port}", display=True)
        while not STOP_RUNNING:
            await asyncio.sleep(1)

        server.close()
        await server.wait_closed()
        verbose_print(f"Stop listening {host}:{port}, exited graceflly", display=True)


async def start_all(
    container_id: str, container_ip: str, remote_user: str, forward_ports: list[int]
):
    server_tasks = [
        start_server(container_id, container_ip, remote_user, port)
        for port in forward_ports
    ]
    # Start container monitoring task
    monitor_task = asyncio.create_task(monitor_container(container_id))

    await asyncio.gather(*server_tasks, monitor_task)


def _docker_command(command: list[str]) -> str:
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        verbose_print(f"Error: {command}", result.stderr)
        exit(1)
    return result.stdout.strip()


def get_remote_user(devcontainer_json, container_id):
    # determine the user to run the command
    remoteUser = "root"
    if devcontainer_json.get("remoteUser"):
        remoteUesr = devcontainer_json.get("remoteUser")
    else:
        metadata: list[dict] = json.loads(
            _docker_command(
                [
                    "docker",
                    "inspect",
                    "-f",
                    '{{ index .Config.Labels "devcontainer.metadata" }}',
                    container_id,
                ]
            )
        )

        for item in metadata:
            if metadata_remote_user := item.get("remoteUser"):
                remoteUser = metadata_remote_user
                break

    verbose_print(f"remoteUser: {remoteUser}")
    return remoteUser


def main():
    # parse json with comments
    # ideally use commentjson or pyjosn5
    # but this will introduce dependency
    jsondata = ""
    with open(".devcontainer/devcontainer.json", "r") as f:
        for line in f:
            jsondata += line.split("//")[0]

    devcontainer_json = json.loads(jsondata)

    forward_ports = devcontainer_json.get("forwardPorts", [])
    if forward_ports:
        # first port
        workspace = os.path.realpath(os.getcwd())
        container_id = _docker_command(
            [
                "docker",
                "ps",
                "-q",
                "-a",
                "--filter",
                f"label=devcontainer.local_folder={workspace}",
                "--filter",
                f"label=devcontainer.config_file={workspace}/.devcontainer/devcontainer.json",
            ]
        )
        container_ip = _docker_command(
            [
                "docker",
                "inspect",
                "-f",
                "{{ .NetworkSettings.IPAddress }}",
                container_id,
            ]
        )
        # determine the user to run the socat command
        remote_user = get_remote_user(devcontainer_json, container_id)

        asyncio.run(start_all(container_id, container_ip, remote_user, forward_ports))


if __name__ == "__main__":
    if len(sys.argv) > 1 and (sys.argv[1].lower() == "verbose"):
        VERBOSE = True

    main()
