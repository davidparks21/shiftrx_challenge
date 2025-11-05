#!/usr/bin/env bash
#===============================================================================
# Script Name   : shell.sh
# Description   : Opens a bash shell inside the docker container at
#                 davidparks21/shiftrx_challenge:latest.
# Usage         : scripts/run.sh
#===============================================================================

IMAGE_NAME="davidparks21/shiftrx_challenge"
TAG="latest"

docker run --rm -it "${IMAGE_NAME}:${TAG}" bash
