#!/usr/bin/env bash
#===============================================================================
# Script Name   : push.sh
# Description   : Pushes the ShiftrX challenge Docker image to Docker Hub.
# Usage         : scripts/push.sh
# Dependencies  : Docker (logged in with 'docker login')
#===============================================================================

IMAGE_NAME="davidparks21/shiftrx_challenge"
TAG="latest"

# Push the latest image to Docker Hub
docker push "${IMAGE_NAME}:${TAG}"
