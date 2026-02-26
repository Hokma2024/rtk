
import asyncio
from mcp.server.stdio import stdio_server
from .tools import mcp 



def main():
    
    mcp.run(transport="stdio")  

if __name__ == "__main__":
    (main())
    print("start")