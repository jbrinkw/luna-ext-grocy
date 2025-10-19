#!/bin/bash
# Start script for Grocy UI
# Args: $1 = port (passed by Luna Hub)

PORT=${1:-5200}

# Install dependencies if needed
if [ ! -d "node_modules" ]; then
    echo "Installing dependencies..."
    npm install
fi

# Start the server
node server.js "$PORT"




