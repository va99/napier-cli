import json
import requests
import os
import logging
from typing import Dict, List, Any, Optional

logger = logging.getLogger("napier.mcp")

class MCPClient:
    """
    MCP Client for communicating with Model Context Protocol servers
    """
    def __init__(self, tool_config: Dict[str, Any]):
        """
        Initialize MCP client with tool configuration
        
        Args:
            tool_config: Dictionary containing tool configuration (url, capabilities, etc.)
        """
        self.tool_id = tool_config.get("id")
        self.name = tool_config.get("name", self.tool_id)
        self.url = tool_config.get("url")
        self.capabilities = tool_config.get("capabilities", [])
    
    def check_connection(self) -> bool:
        """
        Check if the MCP server is running and reachable
        
        Returns:
            bool: True if connection is successful, False otherwise
        """
        if not self.url:
            logger.error(f"No URL defined for tool {self.name}")
            return False
        
        try:
            # MCP specification suggests tools expose a /status endpoint
            response = requests.get(f"{self.url}/status", timeout=2)
            if response.status_code == 200:
                logger.info(f"Successfully connected to {self.name} at {self.url}")
                return True
            else:
                logger.warning(f"Received status code {response.status_code} from {self.name}")
                return False
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to connect to {self.name} at {self.url}: {e}")
            return False
    
    def get_capabilities(self) -> List[str]:
        """
        Get the capabilities of the MCP tool, either from configuration or by querying the tool
        
        Returns:
            List[str]: List of capabilities
        """
        if not self.check_connection():
            return self.capabilities
        
        try:
            # MCP specification suggests tools expose a /capabilities endpoint
            response = requests.get(f"{self.url}/capabilities")
            if response.status_code == 200:
                capabilities = response.json().get("capabilities", [])
                logger.info(f"Got capabilities from {self.name}: {capabilities}")
                return capabilities
            else:
                logger.warning(f"Failed to get capabilities from {self.name}, using configured capabilities")
                return self.capabilities
        except requests.exceptions.RequestException as e:
            logger.error(f"Error getting capabilities from {self.name}: {e}")
            return self.capabilities
    
    def execute_action(self, action: str, params: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Execute an action on the MCP tool
        
        Args:
            action: Action name to execute
            params: Parameters for the action
            
        Returns:
            Dict[str, Any]: Response from the MCP tool
        """
        if not params:
            params = {}
        
        if not self.check_connection():
            return {"error": f"Tool {self.name} is not connected"}
        
        try:
            # MCP specification suggests tools expose action endpoints at /actions/{action}
            response = requests.post(
                f"{self.url}/actions/{action}",
                json=params
            )
            
            if response.status_code == 200:
                logger.info(f"Successfully executed action {action} on {self.name}")
                return response.json()
            else:
                error_msg = f"Failed to execute action {action} on {self.name}: {response.status_code}"
                logger.error(error_msg)
                return {"error": error_msg, "details": response.text}
        except requests.exceptions.RequestException as e:
            error_msg = f"Error executing action {action} on {self.name}: {e}"
            logger.error(error_msg)
            return {"error": error_msg}


class MCPHost:
    """
    MCP Host implementation for managing multiple MCP tools
    """
    def __init__(self, config_path: str):
        """
        Initialize MCP Host with configuration
        
        Args:
            config_path: Path to the configuration file
        """
        self.config_path = config_path
        self.config = self._load_config()
        self.tools: Dict[str, MCPClient] = {}
        self._initialize_tools()
    
    def _load_config(self) -> Dict[str, Any]:
        """
        Load configuration from file
        
        Returns:
            Dict[str, Any]: Configuration dictionary
        """
        if not os.path.exists(self.config_path):
            logger.warning(f"Config file {self.config_path} not found, using empty configuration")
            return {"tools": []}
        
        try:
            with open(self.config_path, "r") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error loading configuration: {e}")
            return {"tools": []}
    
    def _initialize_tools(self):
        """Initialize MCP clients for all tools in configuration"""
        for tool_config in self.config.get("tools", []):
            if tool_config.get("active", True):
                tool_id = tool_config.get("id")
                if tool_id:
                    self.tools[tool_id] = MCPClient(tool_config)
                    logger.info(f"Initialized MCP client for {tool_config.get('name', tool_id)}")
    
    def get_tool(self, tool_id: str) -> Optional[MCPClient]:
        """
        Get an MCP client by tool ID
        
        Args:
            tool_id: Tool ID to retrieve
            
        Returns:
            Optional[MCPClient]: MCP client for the tool, or None if not found
        """
        return self.tools.get(tool_id)
    
    def get_all_tools(self) -> Dict[str, MCPClient]:
        """
        Get all MCP clients
        
        Returns:
            Dict[str, MCPClient]: Dictionary of MCP clients
        """
        return self.tools
    
    def add_tool(self, tool_config: Dict[str, Any]) -> bool:
        """
        Add a new MCP tool to the configuration
        
        Args:
            tool_config: Tool configuration dictionary
            
        Returns:
            bool: True if successful, False otherwise
        """
        tool_id = tool_config.get("id")
        if not tool_id:
            logger.error("Tool ID is required")
            return False
        
        # Add tool to configuration
        self.config.setdefault("tools", []).append(tool_config)
        
        # Save configuration
        try:
            with open(self.config_path, "w") as f:
                json.dump(self.config, f, indent=4)
        except Exception as e:
            logger.error(f"Error saving configuration: {e}")
            return False
        
        # Initialize MCP client for the tool
        self.tools[tool_id] = MCPClient(tool_config)
        logger.info(f"Added MCP tool {tool_config.get('name', tool_id)}")
        
        return True
    
    def remove_tool(self, tool_id: str) -> bool:
        """
        Remove an MCP tool from the configuration
        
        Args:
            tool_id: Tool ID to remove
            
        Returns:
            bool: True if successful, False otherwise
        """
        if tool_id not in self.tools:
            logger.warning(f"Tool {tool_id} not found")
            return False
        
        # Remove tool from configuration
        self.config["tools"] = [t for t in self.config.get("tools", []) if t.get("id") != tool_id]
        
        # Save configuration
        try:
            with open(self.config_path, "w") as f:
                json.dump(self.config, f, indent=4)
        except Exception as e:
            logger.error(f"Error saving configuration: {e}")
            return False
        
        # Remove MCP client
        del self.tools[tool_id]
        logger.info(f"Removed MCP tool {tool_id}")
        
        return True
    
    def check_all_connections(self) -> Dict[str, bool]:
        """
        Check connection to all MCP tools
        
        Returns:
            Dict[str, bool]: Dictionary of tool IDs and connection status
        """
        results = {}
        for tool_id, client in self.tools.items():
            results[tool_id] = client.check_connection()
        return results
    
    def get_all_capabilities(self) -> Dict[str, List[str]]:
        """
        Get capabilities of all MCP tools
        
        Returns:
            Dict[str, List[str]]: Dictionary of tool IDs and capabilities
        """
        capabilities = {}
        for tool_id, client in self.tools.items():
            if client.check_connection():
                capabilities[tool_id] = client.get_capabilities()
        return capabilities
    
    def execute_action(self, tool_id: str, action: str, params: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Execute an action on an MCP tool
        
        Args:
            tool_id: Tool ID to execute action on
            action: Action name to execute
            params: Parameters for the action
            
        Returns:
            Dict[str, Any]: Response from the MCP tool
        """
        client = self.get_tool(tool_id)
        if not client:
            error_msg = f"Tool {tool_id} not found"
            logger.error(error_msg)
            return {"error": error_msg}
        
        return client.execute_action(action, params)