#!/usr/bin/env bash
#===============================================================================
# Script Name   : run.sh
# Description   : Starts the web service inside its docker container at
#                 davidparks21/shiftrx_challenge:latest, runs web services
#                 on port 5000. Intended for local dev use only, the local
#                 app folder is mounted over the docker container files.
# Usage         : scripts/run.sh
#===============================================================================

docker run --rm -it --network host -v "$(pwd)":/shiftrx_challenge davidparks21/shiftrx_challenge:latest
