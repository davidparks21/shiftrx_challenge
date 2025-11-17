#!/usr/bin/env bash
#===============================================================================
# Script Name   : run.sh
# Description   : Starts the web service inside its docker container at
#                 davidparks21/shiftrx_challenge:latest, runs web services
#                 on port 5000. Intended for local dev use only, the local
#                 app folder is mounted over the docker container files.
#                 Also starts `ollama serve` on the host so it can use the
#                 GPU without configuring a GPU enabled container (a simplification
#                 for the POC).
# Usage         : scripts/run.sh
#===============================================================================

# Start ollama on the host if not already running
# Ollama should be run in the container, but an nvidia gpu container takes
# some setup that is being skipped for the POC.
if ! pgrep -x "ollama" >/dev/null; then
  echo "Starting Ollama..."
  ollama serve &
else
  echo "Ollama already running"
fi

docker run --rm -it --network host -v "$(pwd)":/shiftrx_challenge davidparks21/shiftrx_challenge:latest
