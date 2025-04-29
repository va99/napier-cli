import subprocess
import requests
import json
import sys
import os
import signal
import time
from time import sleep
from rich.console import Console
import shutil
from pathlib import Path
import threading
import logging
from rich.logging import RichHandler
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.panel import Panel
from rich.table import Table
import uvicorn
from fastapi import FastAPI, HTTPException, Request
import platform

# Initialize logging
logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
    datefmt="[%X]",
    handlers=[RichHandler(rich_tracebacks=True)]
)
logger = logging.getLogger("napier")

# Initialize console for rich output
console = Console()

# ASCII art greeting
ASCII_ART = """
     ●     ●    
       ╳       
     ●     ●    

 N A P I E R
 
 power to people
"""

# Create FastAPI application for MCP Host
app = FastAPI(title="NAPIER MCP Host", description="Local LLM agent with MCP capabilities")

# Global variables for MCP tools
mcp_tools = []
ollama_process = None
CONFIG_PATH = "config/napier_config.json"
DEFAULT_CONFIG = {
    "name": "napier-cli",
    "description": "Local LLM agent with MCP capabilities",
    "default_model": "llama3",
    "version": "0.1.0",
    "mcp_host": {
        "host": "0.0.0.0",
        "port": 8000
    },
    "ollama": {
        "url": "http://localhost:11434",
        "api_version": "v1"
    },
    "tools": []  # Empty by default, tools will be added through the interface
}

# Function to display animated ASCII art greeting
def animated_greeting(ascii_art, delay=0.05):
    os.system('cls' if os.name == 'nt' else 'clear')
    for line in ascii_art.strip().split('\n'):
        console.print(line, style="bold white")
        sleep(delay)
    console.print("\n[bold green]Welcome to NAPIER - Your Local AI Assistant with MCP![/bold green]\n")

# Function to check if Ollama is installed
def is_ollama_installed():
    return shutil.which("ollama") is not None

# Function to install Ollama automatically
def install_ollama():
    # Detect platform
    system_platform = platform.system()
    
    if system_platform == "Darwin":  # macOS
        console.print("[yellow]macOS detected. Installing Ollama...[/yellow]")
        
        # Try installing with Homebrew if available
        try:
            subprocess.run(["brew", "install", "ollama"], check=True)
            console.print("[bold green]Ollama installed successfully using Homebrew.[/bold green]")
            return True
        except subprocess.CalledProcessError:
            console.print("[bold red]Error: Ollama installation failed via Homebrew. Trying direct installation.[/bold red]")
        
        # If Homebrew installation fails, try downloading the macOS package
        try:
            console.print("[yellow]Downloading Ollama for macOS...[/yellow]")
            # Adjust this URL or method as per Ollama's macOS installation guide if available
            download_url = "https://ollama.com/mac/download"
            subprocess.run(["curl", "-fsSL", download_url, "-o", "ollama.pkg"], check=True)
            subprocess.run(["sudo", "installer", "-pkg", "ollama.pkg", "-target", "/"], check=True)
            console.print("[bold green]Ollama installed successfully for macOS.[/bold green]")
            return True
        except subprocess.CalledProcessError:
            console.print("[bold red]Error: Ollama installation failed. Please check system permissions.[/bold red]")
            return False
            
    elif system_platform == "Linux":  # Linux
        console.print("[yellow]Linux detected. Installing Ollama...[/yellow]")
        
        # Try the original Linux installation method
        try:
            subprocess.run(["curl", "-fsSL", "https://ollama.com/install.sh", "|", "sh"], check=True)
            console.print("[bold green]Ollama installed successfully for Linux.[/bold green]")
            return True
        except subprocess.CalledProcessError:
            console.print("[bold red]Error: Ollama installation failed on Linux.[/bold red]")
            return False
    else:
        console.print("[bold red]Unsupported platform for automatic installation.[/bold red]")
        return False
        
# Function to start Ollama after installation
def start_ollama():
    global ollama_process
    
    console.print("[yellow]Starting Ollama...[/yellow]")
    try:
        # Check if Ollama is already running
        if is_ollama_running():
            console.print("[green]Ollama is already running.[/green]")
            return True
        
        # Start Ollama based on platform
        if platform.system() == "Windows":
            # On Windows, we start Ollama differently
            ollama_process = subprocess.Popen(["ollama", "serve"], 
                                             stdout=subprocess.PIPE, 
                                             stderr=subprocess.PIPE,
                                             creationflags=subprocess.CREATE_NO_WINDOW)
        else:
            # On Unix-like systems
            ollama_process = subprocess.Popen(["ollama", "serve"], 
                                             stdout=subprocess.PIPE, 
                                             stderr=subprocess.PIPE)
        
        # Wait for Ollama to start
        for _ in range(5):
            if is_ollama_running():
                console.print("[bold green]Ollama is now running in the background.[/bold green]")
                return True
            sleep(1)
            
        console.print("[yellow]Waiting for Ollama to start...[/yellow]")
        
        # Check if we can pull the default model
        return True
    except Exception as e:
        console.print(f"[bold red]Error: Failed to start Ollama. {e}[/bold red]")
        return False

# Function to check if Ollama is running
def is_ollama_running():
    try:
        response = requests.get("http://localhost:11434/api/tags")
        return response.status_code == 200
    except requests.exceptions.RequestException:
        return False

# Function to stop Ollama
def stop_ollama():
    global ollama_process
    
    if ollama_process:
        console.print("[yellow]Stopping Ollama...[/yellow]")
        try:
            if platform.system() == "Windows":
                # On Windows, we need to use taskkill
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(ollama_process.pid)], 
                               stderr=subprocess.PIPE, stdout=subprocess.PIPE)
            else:
                # On Unix-like systems
                ollama_process.terminate()
                ollama_process.wait(timeout=5)
                
            console.print("[bold green]Ollama has been stopped.[/bold green]")
        except Exception as e:
            console.print(f"[bold red]Error stopping Ollama: {e}[/bold red]")
    else:
        try:
            # Attempt to kill any running Ollama process
            if platform.system() == "Windows":
                subprocess.run(["taskkill", "/F", "/IM", "ollama.exe"], 
                               stderr=subprocess.PIPE, stdout=subprocess.PIPE)
            else:
                subprocess.run("pkill -f ollama", shell=True, 
                               stderr=subprocess.PIPE, stdout=subprocess.PIPE)
            console.print("[bold green]Ollama has been stopped.[/bold green]")
        except Exception:
            console.print("[yellow]Ollama was not running.[/yellow]")

# Function to load configuration
def load_config():
    global mcp_tools
    
    # Create config directory if it doesn't exist
    config_dir = os.path.dirname(CONFIG_PATH)
    if not os.path.exists(config_dir):
        os.makedirs(config_dir)
    
    # Create config file with default values if it doesn't exist
    if not os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, 'w') as f:
            json.dump(DEFAULT_CONFIG, f, indent=4)
    
    # Load config from file
    try:
        with open(CONFIG_PATH) as f:
            config = json.load(f)
            mcp_tools = config.get("tools", [])
            return config
    except Exception as e:
        console.print(f"[bold red]Error loading configuration: {e}[/bold red]")
        return DEFAULT_CONFIG

# Function to save configuration
def save_config(config):
    try:
        with open(CONFIG_PATH, 'w') as f:
            json.dump(config, f, indent=4)
        console.print("[green]Configuration saved successfully.[/green]")
    except Exception as e:
        console.print(f"[bold red]Error saving configuration: {e}[/bold red]")

# Import MCP implementation
from mcp import MCPHost

# Global variable for MCP Host
mcp_host = None

# Initialize MCP Host
def initialize_mcp_host():
    global mcp_host
    mcp_host = MCPHost(CONFIG_PATH)
    console.print("[green]Initialized MCP Host.[/green]")
    return mcp_host

# Check if necessary MCP tools are installed and running
def ensure_mcp_tools():
    global mcp_tools, mcp_host
    
    if mcp_host is None:
        mcp_host = initialize_mcp_host()
    
    active_tools = [tool for tool in mcp_tools if tool.get("active", True)]
    
    if not active_tools:
        console.print("[yellow]No active MCP tools configured.[/yellow]")
        return
    
    # Check connections to all tools
    connection_status = mcp_host.check_all_connections()
    
    # Start tools that are not running
    for tool in active_tools:
        tool_id = tool.get("id")
        if tool_id in connection_status and not connection_status[tool_id]:
            console.print(f"[yellow]Tool {tool['name']} is not running. Starting it now...[/yellow]")
            start_mcp_tool(tool)
        else:
            console.print(f"[green]{tool['name']} is already running.[/green]")

# Function to check if a specific tool is running
def is_tool_running(tool):
    global mcp_host
    
    if mcp_host is None:
        mcp_host = initialize_mcp_host()
    
    tool_id = tool.get("id")
    if not tool_id:
        return False
    
    client = mcp_host.get_tool(tool_id)
    if client:
        return client.check_connection()
    
    # Fallback to simple URL check if tool is not in MCP Host
    if not tool.get("url"):
        return False
    
    try:
        response = requests.get(tool["url"], timeout=2)
        return response.status_code == 200
    except requests.exceptions.RequestException:
        return False

# Function to start a specific MCP tool
def start_mcp_tool(tool):
    # Check if the tool directory exists
    command_dir = tool.get("command_directory", "./")
    if not os.path.exists(command_dir):
        console.print(f"[bold red]Error: Directory {command_dir} does not exist.[/bold red]")
        return False
    
    # Check if we need to install the tool first
    if tool.get("installation_command") and not os.path.exists(os.path.join(command_dir, "node_modules")):
        console.print(f"[yellow]Installing {tool['name']}...[/yellow]")
        try:
            install_dir = tool.get("installation_directory", command_dir)
            process = subprocess.run(
                tool["installation_command"], 
                shell=True, 
                cwd=install_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            if process.returncode != 0:
                console.print(f"[bold red]Error installing {tool['name']}: {process.stderr.decode()}[/bold red]")
                return False
            console.print(f"[green]{tool['name']} installed successfully.[/green]")
        except Exception as e:
            console.print(f"[bold red]Error installing {tool['name']}: {e}[/bold red]")
            return False
    
    # Start the tool
    try:
        # Split the command into parts if it's not a simple command
        if isinstance(tool["start_command"], list):
            command = tool["start_command"]
        else:
            command = tool["start_command"].split()
        
        # Start the process
        console.print(f"[yellow]Starting {tool['name']}...[/yellow]")
        process = subprocess.Popen(
            command,
            cwd=command_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        
        # Wait a moment to see if the process starts successfully
        time.sleep(2)
        
        # Check if the process is still running
        if process.poll() is None:
            console.print(f"[green]{tool['name']} started successfully.[/green]")
            return True
        else:
            console.print(f"[bold red]Error starting {tool['name']}: {process.stderr.read().decode()}[/bold red]")
            return False
    except Exception as e:
        console.print(f"[bold red]Error starting {tool['name']}: {e}[/bold red]")
        return False

# Function to display the current MCP tool configuration
def display_config():
    config = load_config()
    
    table = Table(title="NAPIER Configuration", show_header=True, header_style="bold magenta")
    table.add_column("Setting", style="dim")
    table.add_column("Value")
    
    table.add_row("Name", config.get("name", "napier-cli"))
    table.add_row("Description", config.get("description", "Local LLM agent with MCP capabilities"))
    table.add_row("Default Model", config.get("default_model", "llama3"))
    
    console.print(table)
    
    # Display tools
    if mcp_tools:
        tools_table = Table(title="MCP Tools", show_header=True, header_style="bold magenta")
        tools_table.add_column("ID", style="dim")
        tools_table.add_column("Name")
        tools_table.add_column("URL")
        tools_table.add_column("Status")
        
        for tool in mcp_tools:
            status = "[green]Running[/green]" if is_tool_running(tool) else "[red]Stopped[/red]"
            tools_table.add_row(
                tool["id"],
                tool["name"],
                tool.get("url", "N/A"),
                status
            )
        
        console.print(tools_table)
    else:
        console.print("[yellow]No MCP tools configured.[/yellow]")

# Add a new MCP tool to the configuration
def add_mcp_tool():
    console.print("[bold green]Add new MCP Tool[/bold green]")
    
    tool_id = input("Tool ID: ").strip()
    tool_name = input("Tool Name: ").strip()
    tool_url = input("Tool URL: ").strip()
    tool_start_command = input("Start Command: ").strip()
    tool_command_directory = input("Command Directory: ").strip()
    tool_capabilities = input("Capabilities (comma-separated): ").strip().split(",")
    
    # Create the new tool
    new_tool = {
        "id": tool_id,
        "name": tool_name,
        "url": tool_url,
        "start_command": tool_start_command,
        "command_directory": tool_command_directory,
        "capabilities": [cap.strip() for cap in tool_capabilities],
        "active": True
    }
    
    # Add optional installation command if provided
    installation_command = input("Installation Command (optional): ").strip()
    if installation_command:
        new_tool["installation_command"] = installation_command
        new_tool["installation_directory"] = input("Installation Directory (optional): ").strip() or tool_command_directory
    
    # Add the tool to the configuration
    config = load_config()
    config["tools"].append(new_tool)
    save_config(config)
    
    # Reload config to update mcp_tools
    load_config()
    
    console.print(f"[bold green]Tool {tool_name} added successfully.[/bold green]")

# Remove an MCP tool from the configuration
def remove_mcp_tool():
    config = load_config()
    
    if not config["tools"]:
        console.print("[yellow]No MCP tools configured.[/yellow]")
        return
    
    console.print("[bold green]Remove MCP Tool[/bold green]")
    
    # Display available tools
    for i, tool in enumerate(config["tools"]):
        console.print(f"{i+1}. {tool['name']} ({tool['id']})")
    
    try:
        choice = int(input("Enter the number of the tool to remove: ").strip())
        if 1 <= choice <= len(config["tools"]):
            tool = config["tools"][choice-1]
            config["tools"].pop(choice-1)
            save_config(config)
            console.print(f"[bold green]Tool {tool['name']} removed successfully.[/bold green]")
            
            # Reload config to update mcp_tools
            load_config()
        else:
            console.print("[bold red]Invalid choice.[/bold red]")
    except ValueError:
        console.print("[bold red]Invalid input. Please enter a number.[/bold red]")

# Function to chat with Ollama locally
def chat_with_ollama():
    config = load_config()
    model = config.get("default_model", "llama3")
    
    ensure_model_available(model)  # <-- NEW LINE HERE

    console.print(f"[bold green]Starting chat with {model}...[/bold green]")
    console.print("[yellow]Type 'exit' to quit, 'change model' to switch models.[/yellow]")
    
    conversation_history = []

    
    while True:
        prompt = input("\nYou: ")
        
        if prompt.lower() == 'exit':
            console.print("[bold green]Chat ended.[/bold green]")
            break
        
        if prompt.lower() == 'change model':
            available_models = get_available_models()
            
            if not available_models:
                console.print("[yellow]No models available. Please pull a model first.[/yellow]")
                continue
            
            console.print("[bold green]Available models:[/bold green]")
            for i, model_name in enumerate(available_models):
                console.print(f"{i+1}. {model_name}")
            
            try:
                choice = int(input("Enter the number of the model to use: ").strip())
                if 1 <= choice <= len(available_models):
                    model = available_models[choice-1]
                    console.print(f"[bold green]Switched to model {model}.[/bold green]")
                    
                    # Update default model in config
                    config = load_config()
                    config["default_model"] = model
                    save_config(config)
                else:
                    console.print("[bold red]Invalid choice.[/bold red]")
            except ValueError:
                console.print("[bold red]Invalid input. Please enter a number.[/bold red]")
            
            continue
        
        # Add prompt to conversation history
        conversation_history.append({"role": "user", "content": prompt})
        
        # Send the request to Ollama
        try:
            with console.status("[bold green]Thinking...[/bold green]"):
                response = requests.post(
                    "http://localhost:11434/api/chat",
                    json={
                        "model": model,
                        "messages": conversation_history
                    }
                )
                
                if response.status_code == 200:
                    assistant_response = response.json()["message"]["content"]
                    console.print(f"\n[bold blue]Assistant:[/bold blue] {assistant_response}")
                    
                    # Add response to conversation history
                    conversation_history.append({"role": "assistant", "content": assistant_response})
                else:
                    console.print(f"[bold red]Error: {response.status_code} - {response.text}[/bold red]")
        except requests.exceptions.RequestException as e:
            console.print(f"[bold red]Error: {e}. Make sure Ollama is running locally.[/bold red]")

# Function to get available models from Ollama
def get_available_models():
    try:
        response = requests.get("http://localhost:11434/api/tags")
        if response.status_code == 200:
            models = response.json().get("models", [])
            return [model["name"] for model in models]
        return []
    except requests.exceptions.RequestException:
        return []

# Function to ensure a model is available; pulls it if not
def ensure_model_available(model_name):
    try:
        response = requests.get("http://localhost:11434/api/tags")
        available_models = response.json().get("models", [])
        if not any(model["name"] == model_name for model in available_models):
            console.print(f"[yellow]Model '{model_name}' not found. Pulling it now...[/yellow]")
            subprocess.run(["ollama", "pull", model_name], check=True)
            console.print(f"[green]Model '{model_name}' pulled successfully.[/green]")
    except Exception as e:
        console.print(f"[red]Failed to pull model '{model_name}': {e}[/red]")

# Function to pull a model from Ollama
def pull_model():
    console.print("[bold green]Pull Model from Ollama[/bold green]")
    
    model_name = input("Model Name (e.g., llama3, llama3:8b, gemma:2b): ").strip()
    
    if not model_name:
        console.print("[bold red]Model name cannot be empty.[/bold red]")
        return
    
    with console.status(f"[bold green]Pulling model {model_name}...[/bold green]"):
        try:
            response = requests.post(
                "http://localhost:11434/api/pull",
                json={"name": model_name}
            )
            
            if response.status_code == 200:
                console.print(f"[bold green]Model {model_name} pulled successfully.[/bold green]")
                
                # Update default model in config
                config = load_config()
                config["default_model"] = model_name
                save_config(config)
            else:
                console.print(f"[bold red]Error pulling model: {response.text}[/bold red]")
        except requests.exceptions.RequestException as e:
            console.print(f"[bold red]Error: {e}. Make sure Ollama is running locally.[/bold red]")

# Function to start the MCP Host API server
def start_mcp_host_server():
    host = "0.0.0.0"
    port = 8000
    
    console.print(f"[bold green]Starting NAPIER MCP Host API at http://{host}:{port}...[/bold green]")
    
    # Run the API server in a separate thread
    threading.Thread(target=lambda: uvicorn.run(app, host=host, port=port), daemon=True).start()
    
    # Wait for the server to start
    time.sleep(2)
    console.print("[bold green]NAPIER MCP Host API is running.[/bold green]")

# API endpoints for MCP Host
@app.get("/")
async def root():
    return {"message": "NAPIER MCP Host API is running", "status": "active"}

@app.get("/tools")
async def list_tools():
    return {"tools": mcp_tools}

@app.get("/tools/{tool_id}")
async def get_tool(tool_id: str):
    tool = next((t for t in mcp_tools if t["id"] == tool_id), None)
    if not tool:
        raise HTTPException(status_code=404, detail=f"Tool {tool_id} not found")
    return tool

@app.post("/tools/{tool_id}/start")
async def start_tool_api(tool_id: str):
    tool = next((t for t in mcp_tools if t["id"] == tool_id), None)
    if not tool:
        raise HTTPException(status_code=404, detail=f"Tool {tool_id} not found")
    
    if is_tool_running(tool):
        return {"message": f"Tool {tool['name']} is already running"}
    
    success = start_mcp_tool(tool)
    if success:
        return {"message": f"Tool {tool['name']} started successfully"}
    else:
        raise HTTPException(status_code=500, detail=f"Failed to start tool {tool['name']}")

@app.post("/chat")
async def chat_api(request: Request):
    data = await request.json()
    
    if "model" not in data or "messages" not in data:
        raise HTTPException(status_code=400, detail="Request must include 'model' and 'messages'")
    
    try:
        response = requests.post(
            "http://localhost:11434/api/chat",
            json=data
        )
        
        if response.status_code == 200:
            return response.json()
        else:
            raise HTTPException(status_code=response.status_code, detail=response.text)
    except requests.exceptions.RequestException as e:
        raise HTTPException(status_code=500, detail=f"Error communicating with Ollama: {str(e)}")

# Interactive menu for NAPIER
def interactive_menu():
    while True:
        console.print("\n[bold green]NAPIER - Local LLM Agent with MCP[/bold green]")
        console.print("[bold white]-----------------------------[/bold white]")
        console.print("1. Chat with LLM")
        console.print("2. View Configuration")
        console.print("3. Add MCP Tool")
        console.print("4. Remove MCP Tool")
        console.print("5. Pull Model from Ollama")
        console.print("6. Start/Restart MCP Tools")
        console.print("7. Exit")
        
        choice = input("\nEnter your choice: ").strip()
        
        if choice == "1":
            chat_with_ollama()
        elif choice == "2":
            display_config()
        elif choice == "3":
            add_mcp_tool()
        elif choice == "4":
            remove_mcp_tool()
        elif choice == "5":
            pull_model()
        elif choice == "6":
            ensure_mcp_tools()
        elif choice == "7":
            console.print("[bold green]Exiting NAPIER...[/bold green]")
            stop_ollama()
            sys.exit(0)
        else:
            console.print("[bold red]Invalid choice. Please try again.[/bold red]")

def ensure_model_available(model_name="llama3"):
    try:
        response = requests.get("http://localhost:11434/api/tags")
        available_models = response.json().get("models", [])
        if not any(model["name"] == model_name for model in available_models):
            console.print(f"[yellow]Model '{model_name}' not found. Pulling it now...[/yellow]")
            subprocess.run(["ollama", "pull", model_name], check=True)
            console.print(f"[green]Model '{model_name}' pulled successfully.[/green]")
    except Exception as e:
        console.print(f"[red]Failed to pull model '{model_name}': {e}[/red]")

# Main program logic
def main():
    # Step 1: Display the animated ASCII art greeting
    animated_greeting(ASCII_ART)
    
    # Step 2: Load configuration
    config = load_config()
    
    # Step 3: Check if Ollama is installed
    if not is_ollama_installed():
        if not install_ollama():
            console.print("[bold red]Ollama is required to run NAPIER. Exiting...[/bold red]")
            sys.exit(1)
    
    # Step 5: Start Ollama
    if not start_ollama():
        console.print("[bold red]Failed to start Ollama. Exiting...[/bold red]")
        sys.exit(1)
    
    # Step 6: Initialize MCP Host
    initialize_mcp_host()
    
    # Step 7: Start the MCP Host API server
    start_mcp_host_server()
    
    # Step 8: Ensure MCP tools are running
    ensure_mcp_tools()
    
    # Step 9: Display the current configuration
    display_config()
    
    # Step 10: Start the interactive menu
    interactive_menu()

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        console.print("\n[bold green]Exiting NAPIER...[/bold green]")
        stop_ollama()
        sys.exit(0)
