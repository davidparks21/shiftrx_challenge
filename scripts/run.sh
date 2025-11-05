#!/usr/bin/env bash
#===============================================================================
# Script Name   : run.sh
# Description   : Starts the web service inside its docker container at
#                 davidparks21/shiftrx_challenge:latest, runs web services
#                 on port 5000.
# Usage         : scripts/run.sh
#===============================================================================

docker run --rm -it --network host --publish 5000:5000 davidparks21/shiftrx_challenge:latest
